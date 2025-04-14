import requests
import time
import logging
import json
import os
import random
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup


# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def get_auth_code(username, password, client_id, redirect_uri):
    session = requests.Session()

    auth_url = 'https://keys.urfu.ru/auth/realms/urfu-lk/protocol/openid-connect/auth'
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': 'some-random-state',
        'response_mode': 'fragment',
        'response_type': 'code',
        'scope': 'openid',
        'nonce': 'some-random-nonce'
    }

    try:
        response = session.get(auth_url, params=params, allow_redirects=True)
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form')
        action_url = form['action']
        inputs = form.find_all('input')
        data = {inp['name']: inp.get('value', '') for inp in inputs if inp.get('name')}

        data['username'] = username
        data['password'] = password

        response = session.post(action_url, data=data, allow_redirects=False)
        redirect_location = response.headers.get('Location')

        parsed_url = urlparse(redirect_location)
        fragment = parsed_url.fragment
        code_data = parse_qs(fragment)

        if 'code' not in code_data:
            logging.error(f"[{username}] Ошибка авторизации: неверный логин или пароль.")
            return None, session

        code = code_data['code'][0]
        logging.info(f"[{username}] Успешная авторизация.")
        return code, session
    except Exception as e:
        logging.exception(f"Ошибка при получении auth code: {e}")
        return None, session


def get_access_token(code, client_id, redirect_uri, session):
    token_url = 'https://keys.urfu.ru/auth/realms/urfu-lk/protocol/openid-connect/token'
    token_data = {
        'code': code,
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'redirect_uri': redirect_uri
    }

    response = session.post(token_url, data=token_data)
    access_token = response.json().get('access_token')
    if access_token:
        logging.info("Access token успешно получен.")
    else:
        logging.warning("Не удалось получить access token.")
    return access_token


def get_current_period(session, access_token):
    url = 'https://teamproject.urfu.ru/api/v2/filters/periods'
    headers = {'Authorization': f'Bearer {access_token}'}
    response = session.get(url, headers=headers).json()
    year = response['current']['year']
    term = response['current']['term']
    logging.info(f"Текущий период: {year} / семестр {term}")
    return year, term


def get_active_projects(session, access_token, year, term):
    url = f'https://teamproject.urfu.ru/api/v2/catalog?status=active&year={year}&semester={term}&size=9&page=1'
    headers = {'Authorization': f'Bearer {access_token}'}
    items = session.get(url, headers=headers).json()['items']
    logging.info(f"Найдено активных проектов: {len(items)}")
    return items


def get_iteration_scores(session, access_token, iteration_id):
    url = f'https://teamproject.urfu.ru/api/v2/iterations/{iteration_id}/scores'
    headers = {'Authorization': f'Bearer {access_token}'}
    response = session.get(url, headers=headers).json()
    return response


# Функция для безопасного получения даты
def get_date_from_dict(info_scores_iter, key, default_value=date.today()):
    date_str = info_scores_iter.get('iteration', {}).get('gradingPeriod', {}).get(key, default_value)
    
    # Проверяем, если значение - строка, пытаемся преобразовать его в datetime.date
    if isinstance(date_str, str):
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_str


def grade_all(session, access_token, projects, student_score, curator_score):
    put_headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    for project in projects:
        project_id = project['id']
        project_name = project.get('title', 'Без названия')
        logging.info(f"Обработка проекта: {project_name} (ID: {project_id})")

        iterations_url = f'https://teamproject.urfu.ru/api/v2/workspaces/{project_id}/iterations'
        iterations = session.get(iterations_url, headers={'Authorization': f'Bearer {access_token}'}).json()

        for iteration in iterations:
            iter_id = iteration['id']
            iter_name = iteration['title']
            
            info_scores_iter = get_iteration_scores(session, access_token, iter_id)

            begin_date = get_date_from_dict(info_scores_iter, 'beginning')
            end_date = get_date_from_dict(info_scores_iter, 'ending')

            if begin_date <= date.today() <= end_date:
                session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/curator',
                            headers=put_headers, data='{"score":'+str(curator_score)+'}')
                logging.info(f"[{project_name}] [{iter_name}] Выставлен балл куратору — оценка {curator_score}")

                for group in info_scores_iter.get('thematicGroups', []):
                    for student in group.get('students', []):
                        student_id = student['studentId']
                        student_name = student['person']['fullname']

                        session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/students/{student_id}',
                                    headers=put_headers, data='{"score":'+str(student_score)+'}')
                        logging.info(f"[{project_name}] [{iter_name}] Студент {student_name} — оценка {student_score}")
            else:
                logging.info(f"[{project_name}] [{iter_name}] Пропускаем итерацию (так как не наступило время для её оценки)")


def process_user(credentials):
    username = credentials['username']
    password = credentials['password']
    client_id = 'teampro'
    redirect_uri = 'https://teamproject.urfu.ru/'
    student_score = os.environ.get("STUDENT_SCORE", "100")
    curator_score = os.environ.get("CURATOR_SCORE", "100")

    code, session = get_auth_code(username, password, client_id, redirect_uri)
    if code is None:
        logging.warning("Прерывание выполнения из-за ошибки авторизации.")
        return

    access_token = get_access_token(code, client_id, redirect_uri, session)
    if not access_token:
        logging.error("Не удалось получить токен, завершение.")
        return

    year, term = get_current_period(session, access_token)
    projects = get_active_projects(session, access_token, year, term)
    grade_all(session, access_token, projects, student_score, curator_score)


def main():
    with open('credentials.json', 'r', encoding='utf-8') as f:
        users = json.load(f)

    while True:
        for credentials in users:
            process_user(credentials)
            delay_users = random.uniform(3, 6)
            time.sleep(delay_users)  # чуть подождать между пользователями

        global_delay = random.uniform(18000, 21600)
        global_delay_hours = global_delay / 3600
        logging.info(f"Цикл завершён. Пауза на {global_delay_hours:.2f} часов.")
        time.sleep(global_delay)


if __name__ == '__main__':
    main()
