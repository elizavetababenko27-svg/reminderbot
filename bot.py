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
user_reminders = {}
user_states = {}


# --- ЧЕК-ЛИСТ ІНТЕРФЕЙС ---

def render_checklist(user_id: int):
    checklist_data = user_checklists.get(user_id, {})
    title = checklist_data.get("title", "Чек-лист")
    items = checklist_data.get("items", [])

    if not items:
        return "✨ **Список порожній**", None

    # Лаконічний заголовок з вашою назвою
    header = f"📋 **{title.upper()}**\n\n"

    keyboard = []
    for idx, item in enumerate(items):
        if item["done"]:
            btn_text = f"✨  ~{item['text']}~"
        else:
            btn_text = f"🔘  {item['text']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"toggle_{idx}")])

    keyboard.append([
        InlineKeyboardButton("➕ Додати", callback_data="add_item"),
        InlineKeyboardButton("🗑 Видалити", callback_data="delete_all")
    ])

    return header, InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "✨ **Бот Чек-листів та Нагадувань**\n\n"
        "• **Створити чек-лист:** `Назва: пункт 1, пункт 2`\n"
        "• **Нагадування:** `/remind Назва 18:30`\n"
        "• **Мої нагадування:** `/myreminders`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def create_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text.strip()

    if user_states.get(user_id, {}).get("step") == "WAITING_FOR_TEXT":
        await process_remind_text(update, context)
        return
    elif user_states.get(user_id, {}).get("step") == "WAITING_FOR_DATETIME":
        await process_remind_datetime(update, context)
        return

    if ":" in raw_text:
        title_part, items_part = raw_text.split(":", 1)
        title = title_part.strip()
    else:
        title = "Чек-лист"
        items_part = raw_text

    delimiter = "," if "," in items_part else "\n"
    items_list = [item.strip().lstrip("-*• ") for item in items_part.split(delimiter) if item.strip()]

    if not items_list:
        return

    user_checklists[user_id] = {
        "title": title,
        "items": [{"text": item, "done": False} for item in items_list]
    }

    text, reply_markup = render_checklist(user_id)
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


# --- НАГАДУВАННЯ (/remind) ---

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if not args:
        user_states[user_id] = {"step": "WAITING_FOR_TEXT"}
        await update.message.reply_text(
            "⏰ **Створення нагадування**\n\nВкажіть текст нагадування:",
            parse_mode="Markdown",
        )
        return

    full_text = " ".join(args)
    await parse_and_schedule_reminder(update, context, full_text)


async def process_remind_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    user_states[user_id]["text"] = text
    user_states[user_id]["step"] = "WAITING_FOR_DATETIME"

    await update.message.reply_text(
        "📅 **Час нагадування** (`18:30` або `15.09 14:30`):",
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

    match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}|\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}|\d{1,2}:\d{2})$", full_text)

    if not match:
        await update.message.reply_text(
            "❌ **Формат не розпізнано.** Спробуйте: `/remind Текст 18:30`",
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
        await update.message.reply_text("❌ Вказано некоректну дату.")
        return

    delay = (target_dt - now).total_seconds()
    
    rem_id = str(int(datetime.datetime.now().timestamp()))
    job = context.job_queue.run_once(
        send_reminder,
        when=delay,
        user_id=user_id,
        data={"title": reminder_title, "repeat": repeat, "id": rem_id},
    )

    if user_id not in user_reminders:
        user_reminders[user_id] = {}

    user_reminders[user_id][rem_id] = {
        "title": reminder_title,
        "time": target_dt,
        "repeat": repeat,
        "job_name": job.name,
    }

    user_states.pop(user_id, None)

    repeat_labels = {"none": "", "daily": " 🔁 щодня", "weekly": " 🔁 щотижня", "monthly": " 🔁 щомісяця"}
    formatted_time = target_dt.strftime("%d.%m.%Y о %H:%M")
    await update.message.reply_text(
        f"⏰ **Нагадування встановлено!**\n\n📌 *{reminder_title}*\n📅 {formatted_time}{repeat_labels[repeat]}",
        parse_mode="Markdown",
    )


# --- КЕРУВАННЯ НАГАДУВАННЯМИ ---

async def my_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminders = user_reminders.get(user_id, {})

    if not reminders:
        await update.message.reply_text("📭 Активних нагадувань немає.")
        return

    keyboard = []
    repeat_labels = {"none": "", "daily": " 🔁", "weekly": " 🔁", "monthly": " 🔁"}

    for rem_id, data in reminders.items():
        time_str = data["time"].strftime("%d.%m %H:%M")
        btn_text = f"⏰ {data['title']} — {time_str}{repeat_labels[data['repeat']]}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"editrem_{rem_id}")])

    await update.message.reply_text(
        "📋 **Ваші нагадування:**",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    title = job.data.get("title", "Нагадування")
    repeat = job.data.get("repeat", "none")
    rem_id = job.data.get("id")

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🔔 **НАГАДУВАННЯ**\n\n{title}",
        parse_mode="Markdown",
    )

    now = datetime.datetime.now()
    next_time = None
    if repeat == "daily":
        next_time = now + datetime.timedelta(days=1)
    elif repeat == "weekly":
        next_time = now + datetime.timedelta(weeks=1)
    elif repeat == "monthly":
        next_time = now + datetime.timedelta(days=30)

    if next_time:
        new_job = context.job_queue.run_once(
            send_reminder,
            when=next_time,
            user_id=user_id,
            data={"title": title, "repeat": repeat, "id": rem_id},
        )
        if user_id in user_reminders and rem_id in user_reminders[user_id]:
            user_reminders[user_id][rem_id]["time"] = next_time
            user_reminders[user_id][rem_id]["job_name"] = new_job.name
    else:
        if user_id in user_reminders:
            user_reminders[user_id].pop(rem_id, None)


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("toggle_"):
        idx = int(data.split("_")[1])
        checklist_data = user_checklists.get(user_id, {})
        items = checklist_data.get("items", [])
        if 0 <= idx < len(items):
            items[idx]["done"] = not items[idx]["done"]
            text, reply_markup = render_checklist(user_id)
            await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

    elif data == "delete_all":
        user_checklists.pop(user_id, None)
        await query.edit_message_text("🗑 **Чек-лист видалено.**")

    elif data == "add_item":
        await query.message.reply_text("✍️ Надішліть нові пункти через кому:")

    elif data.startswith("editrem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).get(rem_id)

        if not remData:
            await query.edit_message_text("❌ Нагадування не знайдено.")
            return

        keyboard = [
            [InlineKeyboardButton("🗑 Видалити", callback_data=f"delrem_{rem_id}")],
            [InlineKeyboardButton("🔄 Змінити", callback_data=f"recreatorem_{rem_id}")],
        ]
        time_str = remData["time"].strftime("%d.%m.%Y %H:%M")
        await query.edit_message_text(
            f"⚙️ **Керування:**\n\n📌 *{remData['title']}*\n📅 {time_str}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("delrem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).pop(rem_id, None)

        if remData:
            current_jobs = context.job_queue.get_jobs_by_name(remData["job_name"])
            for job in current_jobs:
                job.schedule_removal()
            await query.edit_message_text("🗑 **Видалено.**")

    elif data.startswith("recreatorem_"):
        rem_id = data.split("_")[1]
        remData = user_reminders.get(user_id, {}).pop(rem_id, None)

        if remData:
            current_jobs = context.job_queue.get_jobs_by_name(remData["job_name"])
            for job in current_jobs:
                job.schedule_removal()

            user_states[user_id] = {"step": "WAITING_FOR_TEXT"}
            await query.edit_message_text(
                f"📝 **Зміна нагадування**\n\nВведіть новий текст:",
                parse_mode="Markdown",
            )


def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "8765392289:AAEmBrLRy_QqKdfYYj0509VVms1MoH2ud6k")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(CommandHandler("myreminders", my_reminders_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, create_checklist))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    application.run_polling()


if __name__ == "__main__":
    main()
