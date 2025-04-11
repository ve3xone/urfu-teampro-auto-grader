# urfu-teampro-auto-grader

Данный скрипт помогает выставить баллы всем во всех активных проектах на протале teamproject.urfu.ru

## Как поднять скрипт

### Сначала нужно в файле credentials.json нужно ввести свой логин и пароль от учетной записи УРФУ: 
```json
[
  {
    "username": "user1@example.com",
    "password": "your_password1"
  }
]
```

### Также можно ввести несколько учетных записей УРФУ (удобно взять учетки всех участников проектов чтоб автоматический у всех устанавливать нужные баллы):
```json
[
  {
    "username": "user1@example.com",
    "password": "your_password1"
  },
  {
    "username": "user2@example.com",
    "password": "your_password2"
  },
  {
    "username": "user3@example.com",
    "password": "your_password3"
  }
]
```

### Сам запуск скрипта:
```bash
py main.py
```

### Также возможно поднять через docker:
```bash
docker compose up
```
