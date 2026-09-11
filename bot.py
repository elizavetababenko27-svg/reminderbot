import datetime
import logging
import os
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

user_checklists = {}
user_states = {}


# --- ЧЕК-ЛИСТ ИНТЕРФЕЙС ---

def build_checklist_keyboard(user_id: int):
    items = user_checklists.get(user_id, [])
    keyboard = []

    for idx, item in enumerate(items):
        status = "✅ " if item["done"] else "🔲 "
        text = f"{status} {item['text']}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"toggle_{idx}")])

    if items:
        keyboard.append([InlineKeyboardButton("🗑 Видалити чек-лист", callback_data="delete_all")])

    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 **Бот Чек-листів та Нагадувань**\n\n"
        "• **Чек-лист:** Надішліть список через кому або з нового рядка.\n"
        "  *Приклад:* `Купити хліб, попити води, зателефонувати мамі`\n\n"
        "• **Нагадування:** Використовуйте команду `/remind`\n"
        "  *Приклад:* `/remind Прийняти ліки 18:30 щодня`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def create_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text.strip()

    # Якщо користувач у процесі створення нагадування через /remind
    if user_states.get(user_id, {}).get("step") == "WAITING_FOR_TEXT":
        await process_remind_text(update, context)
        return
    elif user_states.get(user_id, {}).get("step") == "WAITING_FOR_DATETIME":
        await process_remind_datetime(update, context)
        return

    # Створення чек-листа
    delimiter = "," if "," in raw_text else "\n"
    items_list = [item.strip().lstrip("-*• ") for item in raw_text.split(delimiter) if item.strip()]

    if not items_list:
        return

    user_checklists[user_id] = [{"text": item, "done": False} for item in items_list]

    reply_markup = build_checklist_keyboard(user_id)
    await update.message.reply_text(
        "📌 **Ваш чек-лист:**",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


# --- ОКРЕМА ЛОГІКА НАГАДУВАНЬ (/remind) ---

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if not args:
        user_states[user_id] = {"step": "WAITING_FOR_TEXT"}
        await update.message.reply_text(
            "⏰ **Створення нагадування**\n\nНапишіть текст нагадування:",
            parse_mode="Markdown",
        )
        return

    # Якщо нагадування введене в один рядок: /remind Купити молоко 15:30
    full_text = " ".join(args)
    await parse_and_schedule_reminder(update, context, full_text)


async def process_remind_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    user_states[user_id]["text"] = text
    user_states[user_id]["step"] = "WAITING_FOR_DATETIME"

    await update.message.reply_text(
        "📅 **Введіть дату та час нагадування.**\n\n"
        "Приклади:\n"
        "• `18:30` (сьогодні або завтра)\n"
        "• `15.09 14:30` (день.місяць час)\n"
        "• `15.09.2026 14:30` (день.місяць.рік час)",
        parse_mode="Markdown",
    )


async def process_remind_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dt_text = update.message.text.strip()
    remind_text = user_states[user_id].get("text", "Нагадування")

    full_text = f"{remind_text} {dt_text}"
    await parse_and_schedule_reminder(update, context, full_text)


async def parse_and_schedule_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, full_text: str):
    user_id = update.effective_user.id
    now = datetime.datetime.now()

    # Перевірка на наявність повтору
    repeat = "none"
    if "щодня" in full_text.lower():
        repeat = "daily"
        full_text = re.sub(r"(?i)\s*щодня", "", full_text)
    elif "щотижня" in full_text.lower():
        repeat = "weekly"
        full_text = re.sub(r"(?i)\s*щотижня", "", full_text)
    elif "щомісяця" in full_text.lower():
        repeat = "monthly"
        full_text = re.sub(r"(?i)\s*щомісяця", "", full_text)

    # Пошук часу та дати в кінці тексту
    match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}|\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}|\d{1,2}:\d{2})$", full_text)

    if not match:
        await update.message.reply_text(
            "❌ **Не вдалося розпізнати дату й час.**\nСпробуйте так: `/remind Текст 18:30`",
            parse_mode="Markdown",
        )
        return

    dt_str = match.group(1)
    reminder_title = full_text[:match.start()].strip() or "Нагадування"

    target_dt = None
    try:
        if re.match(r"^\d{1,2}:\d{2}$", dt_str):
            h, m = map(int, dt_str.split(":"))
            target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target_dt <= now:
                target_dt += datetime.timedelta(days=1)
        elif re.match(r"^\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}$", dt_str):
            day_month, time_part = dt_str.split()
            d, m = map(int, day_month.split("."))
            h, min_p = map(int, time_part.split(":"))
            target_dt = datetime.datetime(now.year, m, d, h, min_p)
            if target_dt <= now:
                target_dt = datetime.datetime(now.year + 1, m, d, h, min_p)
        elif re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}$", dt_str):
            date_part, time_part = dt_str.split()
            d, m, y = map(int, date_part.split("."))
            h, min_p = map(int, time_part.split(":"))
            target_dt = datetime.datetime(y, m, d, h, min_p)
    except Exception:
        target_dt = None

    if not target_dt or target_dt <= now:
        await update.message.reply_text("❌ Вказано час у минулому або некоректну дату.")
        return

    delay = (target_dt - now).total_seconds()
    context.job_queue.run_once(
        send_reminder,
        when=delay,
        user_id=user_id,
        data={"title": reminder_title, "repeat": repeat},
    )

    user_states.pop(user_id, None)

    repeat_labels = {"none": "", "daily": " (щодня)", "weekly": " (щотижня)", "monthly": " (щомісяця)"}
    formatted_time = target_dt.strftime("%d.%m.%Y о %H:%M")
    await update.message.reply_text(
        f"⏰ **Нагадування створено!**\n\n📌 *{reminder_title}*\n📅 {formatted_time}{repeat_labels[repeat]}",
        parse_mode="Markdown",
    )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    title = job.data.get("title", "Нагадування")
    repeat = job.data.get("repeat", "none")

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🔔 **НАГАДУВАННЯ:**\n\n{title}",
        parse_mode="Markdown",
    )

    # Автоматичне планування повтору
    now = datetime.datetime.now()
    next_time = None
    if repeat == "daily":
        next_time = now + datetime.timedelta(days=1)
    elif repeat == "weekly":
        next_time = now + datetime.timedelta(weeks=1)
    elif repeat == "monthly":
        next_time = now + datetime.timedelta(days=30)

    if next_time:
        context.job_queue.run_once(
            send_reminder,
            when=next_time,
            user_id=user_id,
            data={"title": title, "repeat": repeat},
        )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("toggle_"):
        idx = int(data.split("_")[1])
        items = user_checklists.get(user_id, [])
        if 0 <= idx < len(items):
            items[idx]["done"] = not items[idx]["done"]
            await query.edit_message_reply_markup(reply_markup=build_checklist_keyboard(user_id))

    elif data == "delete_all":
        user_checklists.pop(user_id, None)
        await query.edit_message_text("🗑 **Чек-лист видалено.**")


def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "8765392289:AAEmBrLRy_QqKdfYYj0509VVms1MoH2ud6k")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, create_checklist))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    application.run_polling()


if __name__ == "__main__":
    main()
