import requests
import time
import logging
import json
import os
import random
import uuid
from typing import Tuple
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def get_env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        logging.warning("Переменная %s не является числом; будем использовать %d", name, default)
        return default


STUDENT_SCORE = get_env_int("STUDENT_SCORE", 100)
CURATOR_SCORE = get_env_int("CURATOR_SCORE", 100)
LOOP_FLAG = os.environ.get("LOOP_FLAG", "False").lower() == "true"


def get_auth_code(username: str, password: str, client_id: str, redirect_uri: str) -> Tuple[str, requests.Session]:
    session = requests.Session()

    # пореверсил пока хватит простых uuid4
    # TODO: потом ещё посмотрю
    state = str(uuid.uuid4())
    nonce = str(uuid.uuid4())

    auth_url = 'https://keys.urfu.ru/auth/realms/urfu-lk/protocol/openid-connect/auth'
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'state': state,
        'response_mode': 'fragment',
        'response_type': 'code',
        'scope': 'openid',
        'nonce': nonce
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


def get_access_token(session: requests.Session, code: str, client_id: str, redirect_uri: str) -> str:
    token_url = 'https://keys.urfu.ru/auth/realms/urfu-lk/protocol/openid-connect/token'
    token_data = {
        'code': code,
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'redirect_uri': redirect_uri
    }
    try:
        response = session.post(token_url, data=token_data)
        access_token = response.json().get('access_token')
        if access_token:
            logging.info("Access token успешно получен.")
        else:
            logging.error("Не удалось получить access token.")
        return access_token
    except Exception as e:
        logging.exception(f"Ошибка при получении access_token: {e}")
        return None

def get_current_period(session: requests.Session, access_token: str) -> Tuple[str, str]:
    url = 'https://teamproject.urfu.ru/api/v2/filters/periods'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = session.get(url, headers=headers).json()
        year = response.get('current').get('year')
        term = response.get('current').get('term')
        logging.info(f"Текущий период: {year} / семестр {term}")
        return year, term
    except Exception as e:
        logging.exception(f'Ошибка в get_current_period: {e}')
        return None, None


def get_active_projects(session: requests.Session, access_token: str, year: int, term: int) -> list:
    url = f'https://teamproject.urfu.ru/api/v2/catalog?status=active&year={year}&semester={term}&size=9&page=1'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = session.get(url, headers=headers)
    except:
        return []
    
    if response.status_code == 200:
        try:
            data = response.json()
            items = data.get('items', [])
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error [get_active_projects]: {e}")
            logging.info(f"Response content [get_active_projects]: {response.text}")
            items = []
    else:
        items = []

    logging.info(f"Найдено активных проектов: {len(items)}")
    return items


def get_iteration_scores(session: requests.Session, access_token: str, iteration_id: int) -> dict:
    url = f'https://teamproject.urfu.ru/api/v2/iterations/{iteration_id}/scores'
    headers = {'Authorization': f'Bearer {access_token}'}
    response = session.get(url, headers=headers).json()
    return response


def get_date_from_dict(info_scores_iter: dict, key: str, default_value=date.today()) -> datetime.date:
    """Функция для безопасного получения даты"""
    date_str = info_scores_iter.get('iteration', {}).get('gradingPeriod', {}).get(key, default_value)
    
    # Проверяем, если значение - строка, пытаемся преобразовать его в datetime.date
    if isinstance(date_str, str):
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    return date_str


def grade_all(session: requests.Session, access_token: str, projects: list, student_score: int, curator_score: int):
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
            today_date = date.today()
            end_date = get_date_from_dict(info_scores_iter, 'ending')

            if begin_date <= today_date <= end_date:
                session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/curator',
                            headers=put_headers, data='{"score":'+str(curator_score)+'}')
                logging.info(f"[{project_name}] [{iter_name}] Выставлен балл куратору - оценка {curator_score}")

                for group in info_scores_iter.get('thematicGroups', []):
                    for student in group.get('students', []):
                        student_id = student['studentId']
                        student_name = student['person']['fullname']

                        session.put(f'https://teamproject.urfu.ru/api/v2/iterations/{iter_id}/grades/students/{student_id}',
                                    headers=put_headers, data='{"score":'+str(student_score)+'}')
                        logging.info(f"[{project_name}] [{iter_name}] Студент {student_name} - оценка {student_score}")
            elif begin_date < today_date > end_date:
                logging.info(f"[{project_name}] [{iter_name}] Пропускаем итерацию (так как время для её оценки прошло)")
            elif today_date < begin_date and today_date < end_date:
                logging.info(f"[{project_name}] [{iter_name}] Пропускаем итерацию (так как не наступило время для её оценки)")


def process_user(credentials: dict):
    username = credentials['username']
    password = credentials['password']
    client_id = 'teampro'
    redirect_uri = 'https://teamproject.urfu.ru/'

    code, session = get_auth_code(username, password, client_id, redirect_uri)
    if code is None:
        logging.warning("Прерывание выполнения из-за ошибки авторизации.")
        return

    access_token = get_access_token(session, code, client_id, redirect_uri)
    if not access_token:
        logging.error("Оценка была не проставлена, так как не удалось получить токен.")
        return

    year, term = get_current_period(session, access_token)
    if not year:
        logging.warning('Нету года.')
        return
    if not term:
        logging.warning('Нету семестра.')
        return

    projects = get_active_projects(session, access_token, year, term)
    if projects in (None, []):
        return

    grade_all(session, access_token, projects, STUDENT_SCORE, CURATOR_SCORE)


def check_connection(url="https://www.ya.ru"):
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except requests.ConnectionError:
        return False


def main():
    with open('credentials.json', 'r', encoding='utf-8') as f:
        users = json.load(f)
        count_users = len(users)

    while True:
        if check_connection():
            for credentials in users:
                process_user(credentials)
                # чуть подождать между пользователями
                if count_users > 1:
                    delay_users = random.uniform(5, 30)
                    logging.info(f"Ждем между пользователями. Пауза на {delay_users} секунд.")
                    time.sleep(delay_users)

            if not LOOP_FLAG:
                logging.info("Работа завершена после одного прохода. Так как LOOP_FLAG=false.")
                break
        else:
            logging.error('Интернет не доступен.')

        global_delay = random.uniform(18000, 21600)
        global_delay_hours = global_delay / 3600
        logging.info(f"Цикл завершён. Пауза на {global_delay_hours:.2f} часов.")
        time.sleep(global_delay)


if __name__ == '__main__':
    main()
