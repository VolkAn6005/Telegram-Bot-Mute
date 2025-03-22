import logging
import os
from typing import Dict, Any
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackContext,
    filters,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

# Настройка логирования с явным указанием UTF-8
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),  # Указываем UTF-8
        logging.StreamHandler()
    ]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Загрузка токена из .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Глобальная переменная для отслеживания состояния бота
BOT_RUNNING = True

# Твой Telegram ID
MY_ID = 362752154  # @VolkAn6005

def escape_markdown(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!\'"'
    return "".join(
        "\\" + char if char in escape_chars else char for char in text
    )

async def delete_message(context: CallbackContext) -> None:
    """Удаляет сообщение через 30 секунд."""
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

async def start(update: Update, context: CallbackContext) -> None:
    """Обрабатывает вступление нового пользователя."""
    global BOT_RUNNING
    if not BOT_RUNNING:
        return

    try:
        user = update.effective_user
        chat_id = update.effective_chat.id
        logger.info(
            f"Новый пользователь: {user.id} ({user.full_name}) в чате "
            f"{chat_id}"
        )

        chat_member = await context.bot.get_chat_member(
            chat_id=chat_id,
            user_id=user.id,
        )
        if chat_member.status == "creator":
            logger.info(
                f"Пользователь {user.id} — владелец чата, обработка не "
                f"требуется"
            )
            return

        logger.info(
            f"Ограничиваем права пользователя {user.id} в чате {chat_id}"
        )
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions={
                "can_send_messages": False,
                "can_send_media_messages": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False,
            },
        )

        escaped_full_name = escape_markdown(user.full_name)
        message_text = (
            f"Привет, {escaped_full_name}\\! "
            "Чтобы писать в чат, свяжись с администратором\\."
        )
        keyboard = [
            [InlineKeyboardButton("Написать админу", url="https://t.me/frau_ponomareva")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        instruction_message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup,
        )
        logger.info(
            f"Сообщение отправлено: message_id="
            f"{instruction_message.message_id}"
        )

        context.job_queue.run_once(
            delete_message,
            30,
            data={
                "chat_id": chat_id,
                "message_id": instruction_message.message_id,
            },
        )
        logger.info(
            "Задача на удаление сообщения через 30 секунд установлена"
        )
    except Exception as e:
        logger.error(
            f"Ошибка для user_id {user.id} в chat_id {chat_id}: {e}"
        )

async def start_bot(update: Update, context: CallbackContext) -> None:
    """Команда /start для запуска бота."""
    global BOT_RUNNING
    chat_id = update.effective_chat.id
    user = update.effective_user

    chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Только администраторы могут запускать бота."
        )
        return

    if BOT_RUNNING:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот уже запущен!"
        )
    else:
        BOT_RUNNING = True
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот запущен."
        )
    logger.info(f"Бот запущен пользователем {user.id} в чате {chat_id}")

async def stop_bot(update: Update, context: CallbackContext) -> None:
    """Команда /stop для остановки бота."""
    global BOT_RUNNING
    chat_id = update.effective_chat.id
    user = update.effective_user

    chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Только администраторы могут останавливать бота."
        )
        return

    if not BOT_RUNNING:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот уже остановлен!"
        )
    else:
        BOT_RUNNING = False
        await context.bot.send_message(
            chat_id=chat_id,
            text="Бот остановлен."
        )
    logger.info(f"Бот остановлен пользователем {user.id} в чате {chat_id}")

async def send_log(update: Update, context: CallbackContext) -> None:
    """Отправляет последние 100 строк логов @VolkAn6005 по команде /log."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Проверяем, что команду вызывает @VolkAn6005
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
        # Читаем последние 100 строк из файла
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as log_file:
            lines = log_file.readlines()
            last_lines = lines[-100:]  # Берем последние 100 строк
            log_content = "".join(last_lines)

        # Если текст короткий, отправляем как сообщение
        if len(log_content) < 4096:  # Ограничение Telegram на длину сообщения
            await context.bot.send_message(
                chat_id=MY_ID,
                text=f"Последние 100 строк логов:\n```\n{log_content}\n```",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # Если текст длинный, отправляем как файл
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
    """Запускает бота."""
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_bot))
    app.add_handler(CommandHandler("stop", stop_bot))
    app.add_handler(CommandHandler("log", send_log))
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            start,
        )
    )

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()