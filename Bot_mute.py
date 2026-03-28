import logging
import os
import html
from typing import Dict, Any, List
from io import BytesIO
from logging.handlers import RotatingFileHandler
from collections import deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackContext,
    filters,
    ChatMemberHandler,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
# Настройка логирования с явным указанием UTF-8 для корректного отображения кириллицы.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            "bot.log", 
            encoding="utf-8", 
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
# Загрузка токена бота из файла .env.
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Токен бота не найден!")
    raise ValueError("Пожалуйста, укажите BOT_TOKEN в файле .env или в переменных окружения.")

# --- СОСТОЯНИЕ БОТА ---
# Словарь для отслеживания состояния бота в конкретных чатах {chat_id: boolean}.
BOT_RUNNING: Dict[int, bool] = {}

# --- НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ И ЧАТОВ ---
# Telegram ID владельца бота (для доступа к сервисным командам).
MY_ID = 362752154  # @VolkAn6005

# Разрешенные чаты (ID групп, в которых боту разрешено работать).
# Если список пуст [] - бот работает везде. 
# Для работы в нескольких чатах перечислите их через запятую: [-100123456789, -100987654321, -100112233445].
ALLOWED_CHATS = []  # Пример: [-100123456789]

# --- НАСТРОЙКИ СООБЩЕНИЙ ---
# Ссылка на администратора для кнопки связи.
ADMIN_CONTACT_URL = "https://t.me/frau_ponomareva"

# Текст приветственного сообщения для новичков.
# Примечание: Специальные символы будут экранированы автоматически.
WELCOME_MESSAGE_TEXT = "Привет, {full_name}! Чтобы писать в чат, свяжись с администратором."

# Множество для отслеживания уже обработанных новых участников, чтобы избежать дублирования действий.
PROCESSED_USERS = set()

def escape_markdown(text: str) -> str:
    """
    Экранирует специальные символы для корректного отображения в формате MarkdownV2.
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!\'"\\'
    return "".join(
        "\\" + char if char in escape_chars else char for char in text
    )

async def delete_message(context: CallbackContext) -> None:
    """
    Удаляет сообщение бота по истечении заданного времени (применяется через JobQueue).
    """
    job_data: Dict[str, Any] = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
        logger.info(
            f"Сообщение {message_id} удалено из чата {chat_id}"
        )
    except Exception as e:
        logger.error(
            f"Ошибка при удалении сообщения {message_id} из чата "
            f"{chat_id}: {e}"
        )

async def remove_from_processed(context: CallbackContext) -> None:
    """
    Удаляет ключ пользователя из списка обработанных через некоторое время (для очистки памяти).
    """
    user_key = context.job.data
    PROCESSED_USERS.discard(user_key)
    logger.info(f"Ключ {user_key} удален из списка обработанных по таймеру.")

async def start(update: Update, context: CallbackContext) -> None:
    """
    Обрабатывает событие вступления нового пользователя в чат.
    Ограничивает права на отправку любых сообщений и выдает инструкцию.
    """
    try:
        chat = update.effective_chat
        chat_id = chat.id
        
        # Проверка на нахождение чата в белом списке (если он задан).
        
        if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
            logger.warning(f"Неразрешенный чат {chat_id}. Покидаем чат.")
            await context.bot.leave_chat(chat_id)
            return

        # Установка состояния по умолчанию - бот включен.
        is_running = BOT_RUNNING.get(chat_id, True)
        if not is_running:
            return

        # Формирование списка новых пользователей для обработки.
        users_to_process = []
        if update.message and update.message.new_chat_members:
            users_to_process = update.message.new_chat_members
        elif update.chat_member:
            users_to_process = [update.chat_member.new_chat_member.user]
        
        for user in users_to_process:
            if user.is_bot:
                continue

            user_key = f"{chat_id}:{user.id}"  # Уникальный ключ для сочетания чата и пользователя.

            # Пропуск обработки, если пользователь уже был обработан ранее.
            if user_key in PROCESSED_USERS:
                logger.info(f"Пользователь {user.id} ({user.full_name}) уже обработан в чате {chat_id}, пропускаем")
                continue

            logger.info(f"Новый пользователь: {user.id} ({user.full_name}), чат {chat_id}")

            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id=chat_id,
                    user_id=user.id,
                )
                if chat_member.status in ["creator", "administrator"]:
                    logger.info(
                        f"Пользователь {user.id} — администратор или создатель, обработка не "
                        f"требуется"
                    )
                    continue
                if chat_member.status == "restricted" and not chat_member.can_send_messages:
                    logger.info(f"Права пользователя {user.id} уже ограничены в чате {chat_id}")
                    PROCESSED_USERS.add(user_key)
                    # Планируем очистку через 10 минут, если JobQueue доступен.
                    if context.job_queue:
                        context.job_queue.run_once(remove_from_processed, 600, data=user_key)
                    else:
                        logger.warning("JobQueue недоступен, очистка PROCESSED_USERS не будет запланирована.")
                    continue
            except Exception as e:
                logger.error(f"Ошибка при получении информации о участнике {user.id}: {e}")
                continue

            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                    ),
                )
            except Exception as e:
                logger.error(f"Ошибка при ограничении прав пользователя {user.id}: {e}")
                continue

            try:
                # Формируем текст сообщения из настроек.
                # В MarkdownV2 нужно экранировать имя пользователя и остальной текст отдельно.
                escaped_full_name = escape_markdown(user.full_name)
                message_text = escape_markdown(WELCOME_MESSAGE_TEXT).replace(
                    "\\{full\\_name\\}", escaped_full_name
                )
                
                keyboard = [
                    [InlineKeyboardButton("Написать админу", url=ADMIN_CONTACT_URL)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                instruction_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup,
                )
                if context.job_queue:
                    context.job_queue.run_once(
                        delete_message,
                        30,
                        data={
                            "chat_id": chat_id,
                            "message_id": instruction_message.message_id,
                        },
                    )
                else:
                    logger.warning("JobQueue недоступен, сообщение не будет удалено автоматически.")

                logger.info(f"✅ {user.full_name} ({user.id}) ограничен, msg={instruction_message.message_id}, чат {chat_id}")

                PROCESSED_USERS.add(user_key)
                
                # Планируем очистку через 10 минут, если JobQueue доступен.
                if context.job_queue:
                    context.job_queue.run_once(remove_from_processed, 600, data=user_key)
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения пользователю {user.id}: {e}")

    except Exception as e:
        logger.error(
            f"Общая ошибка в обработке start для chat_id {update.effective_chat.id if update.effective_chat else 'Unknown'}: {e}"
        )

async def chat_member_update(update: Update, context: CallbackContext) -> None:
    """
    Обрабатывает системные события об изменении статуса участников чата.
    Служит дополнительным триггером для выявления новых пользователей.
    """
    member_update = update.chat_member
    if member_update is None:
        logger.warning("update.chat_member пустой, пропускаем обработку")
        return
        
    chat_id = member_update.chat.id
    
    if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
        logger.warning(f"Получено обновление из неразрешенного чата {chat_id}. Покидаем чат.")
        try:
            await context.bot.leave_chat(chat_id)
        except Exception:
            pass
        return

    is_running = BOT_RUNNING.get(chat_id, True)
    if not is_running:
        logger.info(f"Бот остановлен для чата {chat_id}, обработка обновлений статуса пропущена")
        return

    old_status = member_update.old_chat_member.status
    new_status = member_update.new_chat_member.status
    user = member_update.new_chat_member.user

    if old_status != new_status:
        if new_status == "member" and old_status in ["left", "kicked"]:
            logger.info(f"Новый участник {user.id} ({user.full_name}) вступил в чат {chat_id} (через ChatMemberHandler)")
            await start(update, context)  # Обрабатываем только настоящее вступление
        elif new_status == "left":
            logger.info(f"Пользователь {user.id} ({user.full_name}) вышел из чата {chat_id}")
            user_key = f"{chat_id}:{user.id}"
            PROCESSED_USERS.discard(user_key)
        elif new_status in ["administrator", "creator"]:
            logger.info(f"Пользователь {user.id} ({user.full_name}) стал {new_status} в чате {chat_id}")
        else:
            logger.debug(f"Статус {user.id} ({user.full_name}): {old_status} → {new_status}, чат {chat_id}")
    else:
        logger.debug(f"Статус {user.id} ({user.full_name}) не изменился: {old_status}")

async def check_admin_permissions(update: Update, context: CallbackContext) -> bool:
    """
    Проверяет, является ли чат групповым, разрешенным и является ли пользователь администратором.
    Возвращает True, если проверки пройдены, иначе отправляет сообщение и возвращает False.
    """
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    if chat.type == "private":
        await context.bot.send_message(
            chat_id=chat_id,
            text="Эта команда доступна только в группах."
        )
        return False

    if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Работа в этом чате запрещена. Бот отключается."
        )
        await context.bot.leave_chat(chat_id)
        return False

    chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Только администраторы могут управлять ботом."
        )
        return False

    return True

async def start_bot(update: Update, context: CallbackContext) -> None:
    """
    Команда /start. 
    Включает функционал ограничения новых пользователей (мут) в конкретном чате.
    """
    if not await check_admin_permissions(update, context):
        return

    chat_id = update.effective_chat.id
    is_running = BOT_RUNNING.get(chat_id, True)
    if is_running:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот уже запущен в этом чате!"
        )
    else:
        BOT_RUNNING[chat_id] = True
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот запущен в этом чате."
        )
    logger.info(f"Бот запущен пользователем {update.effective_user.id} в чате {chat_id}")

async def stop_bot(update: Update, context: CallbackContext) -> None:
    """
    Команда /stop.
    Отключает функционал ограничения новых пользователей (мут) в конкретном чате.
    """
    if not await check_admin_permissions(update, context):
        return

    chat_id = update.effective_chat.id
    is_running = BOT_RUNNING.get(chat_id, True)
    if not is_running:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот уже остановлен в этом чате!"
        )
    else:
        BOT_RUNNING[chat_id] = False
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот остановлен в этом чате."
        )
    logger.info(f"Бот остановлен пользователем {update.effective_user.id} в чате {chat_id}")


async def send_log(update: Update, context: CallbackContext) -> None:
    """
    Команда /log.
    Доступна только владельцу бота. Отправляет последние 100 строк лог-файла.
    При превышении лимита символов в сообщении, отправляет логи в виде текстового файла.
    """
    chat_id = update.effective_chat.id
    user = update.effective_user

    if user.id != MY_ID:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Эта команда доступна только ответственному за бота."
        )
        return

    log_file_path = "bot.log"
    if not os.path.exists(log_file_path):
        await context.bot.send_message(
            chat_id=chat_id,
            text="Лог-файл не найден."
        )
        return

    try:
        # Эффективное чтение последних 100 строк без загрузки всего файла в память.
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as log_file:
            last_lines = deque(log_file, maxlen=100)
            log_content = "".join(last_lines)

        if len(log_content) < 4000:
            # Экранируем HTML символы, чтобы логи не сломали разметку.
            escaped_log = html.escape(log_content)
            await context.bot.send_message(
                chat_id=MY_ID,
                text=f"Последние 100 строк логов:\n<pre>{escaped_log}</pre>",
                parse_mode=ParseMode.HTML
            )
        else:
            log_bytes = log_content.encode("utf-8")
            log_file_io = BytesIO(log_bytes)
            log_file_io.name = "last_100_logs.txt"
            await context.bot.send_document(
                chat_id=MY_ID,
                document=log_file_io,
                filename="last_100_logs.txt",
                caption="Последние 100 строк логов."
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text="Последние 100 строк логов отправлены тебе в личку."
        )
        logger.info(f"Последние 100 строк логов отправлены @VolkAn6005 (ID: {MY_ID})")
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ошибка при отправке лога: {e}"
        )
        logger.error(f"Ошибка при отправке лога @VolkAn6005 (ID: {MY_ID}): {e}")

def main() -> None:
    """
    Точка входа. Инициализирует бота и регистрирует обработчики событий.
    """
    # Инициализация приложения. 
    # JobQueue теперь требует установленной библиотеки apscheduler.
    app = Application.builder().token(TOKEN).build()

    if not app.job_queue:
        logger.warning("JobQueue не инициализирован! Убедитесь, что установлена библиотека apscheduler (pip install apscheduler). Автоматическое удаление сообщений не будет работать!")

    app.add_handler(CommandHandler("start", start_bot))
    app.add_handler(CommandHandler("stop", stop_bot))
    app.add_handler(CommandHandler("log", send_log))

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            start,
        )
    )

    app.add_handler(
        ChatMemberHandler(
            chat_member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=["message", "chat_member"])

if __name__ == "__main__":
    main()