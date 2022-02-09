import hashlib
import hmac
import os
import requests
from telebot import types, apihelper

from telebot import TeleBot

apihelper.ENABLE_MIDDLEWARE = True
bot = TeleBot(os.environ.get('TOKEN'), parse_mode='markdown')
admin_id = 256711367

tt_tokens = {}
tt_token = None


def get_token(bot_instance, chat):
    data = {
        'id': chat.id,
        'first_name': chat.first_name,
        'last_name': chat.last_name,
        'username': chat.username,
    }
    print(data)
    data = dict(sorted(data.items(), key=lambda x: x[0]))
    validation_string = "\n".join(f"{i[0]}={i[1]}" for i in data.items()).encode("UTF-8")
    check_hash = hmac.new(key=bot_instance.token.encode("UTF-8"),
                          msg=validation_string,
                          digestmod=hashlib.sha256).hexdigest()
    data |= {'hash': check_hash}
    tt_response = requests.get("http://127.0.0.1:5000/user/get_token", json=data)
    resp = tt_response.json()
    try:
        tt_tokens[chat.id] = resp['token']
    except KeyError:
        bot_instance.send_message(chat.id, "А ой. Кажется что-то сломалось🙃\n"
                                           "Отчет уже отправлен разработчикам. Приносим свои извинения")
        bot_instance.send_message(admin_id, "‼️ Сбой при попытке получить токен ‼️\n"
                                            f"Chat: {chat}\n\n"
                                            f"Server response: {resp}")
        return None
    return tt_tokens[chat.id]


@bot.middleware_handler(update_types=['message', 'callback_query'])
def load_user(bot_instance, entity):
    global tt_token
    if type(entity) == types.CallbackQuery:
        tt_token = tt_tokens.get(entity.message.chat.id) or get_token(bot_instance, entity.message.chat)
    else:
        if entity.successful_payment: print(entity)
        tt_token = tt_tokens.get(entity.chat.id) or get_token(bot_instance, entity.chat)


def make_request(link: str, method: str = "GET", data: dict = None):
    headers = {'Authorization': f"Bearer {tt_token}"}
    if link.startswith('/'):
        link = f"http://127.0.0.1:5000{link}"
    elif not link.startswith('http'):
        link = f"http://127.0.0.1:5000/{link}"
    r = requests.request(method=method, url=link, headers=headers, json=data)
    if r.status_code != 200:
        raise requests.RequestException(r.status_code, r.json())
    return r.json()


def generate_keyboard(task_or_tasks: dict or list):
    mp = types.InlineKeyboardMarkup(row_width=1)
    if type(task_or_tasks) is list:
        for task in task_or_tasks:
            mp.add(
                types.InlineKeyboardButton(f"🔳 {task['title']}",
                                           callback_data=f"http://127.0.0.1:5000/task/{task['id']}")
            )
        mp.add(
            types.InlineKeyboardButton("🆕 New tree", callback_data="new~http://127.0.0.1:5000/tasks")
        )
        return mp
    task = task_or_tasks
    mp.add(
        types.InlineKeyboardButton("🔙 Back",
                                   callback_data=task['parent_uri'] or "http://127.0.0.1:5000/tasks?filter=roots")
    )
    for st_uri in task['subtasks_uris']:
        subtask = make_request(st_uri)
        mp.add(
            types.InlineKeyboardButton(f"▫️ {subtask['title']}", callback_data=st_uri)
        )
    mp.row(
        types.InlineKeyboardButton("✏️ Edit", callback_data=f"edit~http://127.0.0.1:5000/task/{task['id']}"),
        types.InlineKeyboardButton("❌ Delete", callback_data=f"del~http://127.0.0.1:5000/task/{task['id']}")
    )
    mp.add(
        types.InlineKeyboardButton("🆕 New task", callback_data=f"new~http://127.0.0.1:5000/task/{task['id']}")
    )
    return mp


@bot.message_handler(commands=['start'])
def start(msg):
    tasks = make_request('/tasks?filter=roots')
    roots = list(filter(lambda task: task['parent_uri'] is None, tasks))  # TODO: task
    if len(roots) == 0:
        text = "Create your first tree:"
    else:
        text = "Your trees:"
    bot.send_message(msg.chat.id, text, reply_markup=generate_keyboard(roots))
    bot.delete_message(msg.chat.id, msg.message_id)


@bot.message_handler(commands=['test_payment'])
def test_payment(msg):
    mk = types.InlineKeyboardMarkup()
    mk.add(
        types.InlineKeyboardButton("Деньги на бочку!", pay=True),
        types.InlineKeyboardButton("Нет!", callback_data="NO")
    )
    bot.send_invoice(
        msg.chat.id,
        title="Title of invoice",
        description="Description of invoice",
        invoice_payload="Payload of invoice",
        provider_token="401643678:TEST:fd14deb5-4faa-45ee-b32e-5c02dce469c9",  # Сбербанк TEST
        # provider_token="284685063:TEST:ZjI4ZDE1YWI2MjMx ",  # Stripe TEST
        currency="rub",
        prices=[
            types.LabeledPrice("Label of price 1", amount=729),
            types.LabeledPrice("Label of price 2", amount=1000),
        ],
        reply_markup=mk,
        # start_parameter="https://t.me/TaskTreeBot?start=start",
        # photo_url="https://upload.wikimedia.org/wikipedia/commons/0/0b/Cat_poster_1.jpg",
        photo_size=1000,
        max_tip_amount=10000,
        suggested_tip_amounts=[
            200,
            300
        ]
    )


@bot.pre_checkout_query_handler(func=lambda c: True)
def test_pcq(q: types.PreCheckoutQuery):
    print(q)
    bot.answer_pre_checkout_query(q.id, ok=True)


@bot.message_handler(content_types='successful_payment')
def test_cq(msg: types.Message):
    print("Confirm:", msg.successful_payment)
    bot.send_message(msg.chat.id, "Спасибо за оплату")


new_messages_process = {}


@bot.callback_query_handler(func=lambda c: c.data.startswith('new'))
def create_new_task(c: types.CallbackQuery):
    snt = bot.send_message(chat_id=c.message.chat.id, text="Enter title of new task:",
                           reply_markup=types.ForceReply(input_field_placeholder="Enter title..."))
    bot.register_for_reply(snt, process_title)
    bot.delete_message(c.message.chat.id, c.message.message_id)

    _, uri = c.data.split('~')
    new_messages_process[c.message.chat.id] = {'parent_uri': uri}
    bot.answer_callback_query(c.id, text="Enter title")


def process_title(msg: types.Message):
    new_messages_process[msg.chat.id]['title'] = msg.text
    mp = types.InlineKeyboardMarkup(row_width=1)
    mp.add(
        types.InlineKeyboardButton("Add description", callback_data="desc"),  # TODO: add description
        types.InlineKeyboardButton("Done", callback_data="confirm_new")
    )
    bot.send_message(msg.chat.id, f"New task:\n*Title:* {msg.text}", reply_markup=mp)
    bot.delete_message(msg.chat.id, msg.message_id)
    bot.delete_message(msg.chat.id, msg.reply_to_message.message_id)


@bot.callback_query_handler(func=lambda c: c.data == 'desc')
def description(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    snt = bot.send_message(c.message.chat.id, "Введите описание:",
                           reply_markup=types.ForceReply(input_field_placeholder="Ввести описание..."))
    bot.register_for_reply(snt, )


@bot.callback_query_handler(func=lambda c: c.data == "confirm_new")
def confirm_new_message(c: types.CallbackQuery):
    new_msg = new_messages_process.pop(c.message.chat.id)
    new_task = make_request(new_msg["parent_uri"], method='POST', data=new_msg)
    bot.edit_message_text(f"*{new_task['title']}*\n\n{new_task['description'] or ''}",
                          c.message.chat.id, c.message.message_id, reply_markup=generate_keyboard(new_task))
    bot.answer_callback_query(c.id, text="Created!")


@bot.callback_query_handler(func=lambda c: c.data.startswith("http"))
def main_message(c):
    task = make_request(c.data)
    if type(task) is list:
        task = list(filter(lambda t: t['parent_uri'] is None, task))  # TODO: task
    text = f"*{task['title']}*\n\n{task['description'] or ''}" if type(task) is dict else "Your trees: "
    bot.edit_message_text(text=text,
                          chat_id=c.message.chat.id,
                          message_id=c.message.message_id,
                          reply_markup=generate_keyboard(task))
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith('del'))
def delete_task(c):
    _, uri = c.data.split('~')
    deleted_task = make_request(uri, method="DELETE")
    c.data = deleted_task['parent_uri'] or "http://127.0.0.1:5000/tasks?filter=roots"
    main_message(c)
    bot.answer_callback_query(c.id, "Deleted!")


print("Running...")
bot.polling(skip_pending=True, non_stop=True)
