import requests
import time
import logging
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


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

            session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/curator',
                        headers=put_headers, data='{"score":'+str(curator_score)+'}')
            logging.info(f"[{project_name}] [{iter_name}] Выставлен балл куратору — оценка {curator_score}")

            scores_url = f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/scores'
            scores = session.get(scores_url, headers={'Authorization': f'Bearer {access_token}'}).json()

            for group in scores.get('thematicGroups', []):
                for student in group.get('students', []):
                    student_id = student['studentId']
                    student_name = student['person']['fullname']

                    session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/students/{student_id}',
                                headers=put_headers, data='{"score":'+str(student_score)+'}')
                    logging.info(f"[{project_name}] [{iter_name}] Студент {student_name} — оценка {student_score}")


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
            time.sleep(5)  # чуть подождать между пользователями

        logging.info("Цикл завершён. Пауза на 6 часов.")
        time.sleep(21600)  # каждые 6 часов


if __name__ == '__main__':
    main()
