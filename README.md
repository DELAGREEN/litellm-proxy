# 🚀 LiteLLM Proxy для VS Code (в обход Cloudflare)

Этот репозиторий содержит локальный прокси-сервер, который позволяет использовать модели (например, `deepseek/deepseek-v4-flash`) через ваш LiteLLM-роутер прямо в VS Code, обходя при этом блокировки Cloudflare.

## 🤔 Зачем это нужно?

VS Code (и его расширения) работают на Node.js. Cloudflare на стороне вашего LiteLLM-сервера блокирует запросы от Node.js из-за специфического TLS-отпечатка (ошибка `403 Just a moment...`). 

Этот прокси перехватывает запросы от VS Code, пересоздает их с TLS-отпечатком браузера **Safari** (с помощью библиотеки `curl_cffi`) и отправляет в LiteLLM. Для VS Code всё выглядит так, будто он общается с обычным локальным сервером.

## 🛠️ Установка и настройка прокси

### Шаг 1: Клонирование и зависимости
Убедитесь, что у вас установлен Python 3.8+.

```bash
# Создаем виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Для Windows: venv\Scripts\activate

# Устанавливаем зависимости
pip install flask curl_cffi python-dotenv
```

### Шаг 2: Настройка окружения (.env)
Создайте файл `.env` в корне проекта и заполните его своими данными:

```env
UPSTREAM_URL=https://litellm.ishosting.com
LITELLM_API_KEY=ваш_рабочий_ключ_litellm
PROXY_PORT=8081
```
*(Убедитесь, что `.env` добавлен в `.gitignore`!)*

### Шаг 3: Запуск прокси
```bash
python main.py
```
Оставьте этот терминал открытым. В логах должно появиться:
`🚀 LiteLLM proxy запущен на http://127.0.0.1:8081/v1`

---

## 💻 Настройка VS Code

У вас есть два способа подключить прокси к VS Code. Мы рекомендуем **Способ 1**, так как он дает больше контроля и поддерживает агентский режим.

### Способ 1: Расширение Matrix OAI Gateway (Рекомендуемый)

Это расширение позволяет добавлять кастомные модели прямо в стандартный интерфейс GitHub Copilot Chat.

1. Перейдите в раздел расширений VS Code (`Ctrl+Shift+X`).
2. Найдите и установите **Matrix OAI Gateway for Copilot** (автор: *matrix*).
3. Откройте файл настроек `settings.json` (`Ctrl+Shift+P` -> `Preferences: Open User Settings (JSON)`).
4. Добавьте туда конфигурацию провайдера и модели (если у вас уже что-то есть, просто добавьте эти блоки внутрь существующих массивов):

```json
{
    "matrixOaiCopilot.providers": [
        {
            "id": "ishosting",
            "name": "ishosting (LiteLLM via proxy)",
            "baseUrl": "http://127.0.0.1:8081/v1",
            "apiMode": "openai",
            "headers": {}
        }
    ],
    "matrixOaiCopilot.models": [
        {
            "id": "deepseek-v4-flash",
            "name": "DeepSeek V4 Flash (via proxy)",
            "providerId": "ishosting",
            "family": "deepseek",
            "version": "deepseek-v4-flash",
            "maxInputTokens": 1000000,
            "maxOutputTokens": 393216,
            "context_length": 1000000,
            "supportsTools": true,
            "supportsImages": false,
            "stream": true
        }
    ],
    "matrixOaiCopilot.copilot.abliterProxyModel": "deepseek-v4-flash"
}
```

> **Важно**: Обратите внимание на поле `"id"`. В VS Code мы пишем `deepseek-v4-flash` (без слэша), так как VS Code не любит слэши в ID. Прокси сам заменит его на правильный `deepseek/deepseek-v4-flash` перед отправкой в LiteLLM.

### Способ 2: Встроенный Custom Endpoint (Запасной)

Если вы не хотите ставить сторонние расширения, можно использовать встроенный механизм.

1. Откройте палитру команд (`Ctrl+Shift+P`).
2. Введите **`Chat: Manage Language Models`** и выберите эту команду.
3. Нажмите **Add Models** -> **Custom Endpoint**.
4. В открывшемся файле `chatLanguageModels.json` приведите конфигурацию к виду:

```json
[
	{
		"name": "DeepSeek (via proxy)",
		"vendor": "customendpoint",
		"apiKey": "${input:chat.lm.secret.ваш_секрет}",
		"apiType": "chat-completions",
		"models": [
			{
				"id": "deepseek-v4-flash",
				"name": "DeepSeek V4 Flash (Proxy)",
				"url": "http://127.0.0.1:8081/v1/chat/completions",
				"toolCalling": true,
				"vision": false,
				"maxInputTokens": 1000000,
				"maxOutputTokens": 393216
			}
		]
	}
]
```

---

## ⚠️ Критически важный шаг: Включение модели!

После того как вы сохранили настройки (любым из способов):
1. Нажмите `Ctrl+Shift+P` -> **`Developer: Reload Window`**.
2. Подождите 10–15 секунд.
3. Откройте чат VS Code. В выпадающем списке выберите вашу модель (**DeepSeek V4 Flash (via proxy)**).
4. **Убедитесь, что модель включена!** Зайдите в меню управления моделями (для Способа 1 — настройки расширения Matrix, для Способа 2 — `Chat: Manage Language Models`), найдите вашу модель и проверьте, что напротив неё горит иконка глаза (или стоит галочка). Если модель выключена, VS Code будет выдавать ошибку `"The selected model is not available"`, даже не пытаясь отправить запрос на прокси.

---

## 🔍 Диагностика

Если что-то не работает, смотрите в консоль, где запущен `main.py`:
* Если при отправке сообщения в чате VS Code в консоли **нет** строк `[PROXY] POST ...`, значит VS Code даже не пытается обратиться к прокси (модель выключена, выбран не тот ID, или не сделан Reload Window).
* Если в консоли есть `[PROXY] POST ...`, но VS Code выдает ошибку — значит запрос ушел, но LiteLLM вернул ошибку (проверьте ключ в `.env`).
* Если вы видите HTML с текстом `Just a moment...` — значит Cloudflare обновил защиту. Обновите библиотеку: `pip install -U curl_cffi`.

## 🏃‍♂️ Автозапуск (опционально)

Чтобы не держать терминал открытым, можно запустить прокси в фоне:
```bash
nohup python main.py > proxy.log 2>&1 &
```