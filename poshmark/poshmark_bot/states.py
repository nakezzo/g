from aiogram.fsm.state import State, StatesGroup

class AddAccount(StatesGroup):
    email    = State()
    password = State()

class SetLimit(StatesGroup):
    waiting = State()

class EditVar(StatesGroup):
    values = State()

class EditSubject(StatesGroup):
    subjects = State()

class AddTemplate(StatesGroup):
    name    = State()
    content = State()
    file    = State()

class SendMail(StatesGroup):
    recipients = State()
    confirm    = State()

class ParserSettings(StatesGroup):
    waiting = State()

class EditDelay(StatesGroup):
    waiting = State()

class EditRotation(StatesGroup):
    waiting = State()

class ApiParserSt(StatesGroup):
    interval = State()
    token    = State()
    platform = State()
    country  = State()
    category = State()
    price    = State()
    limit    = State()
    pub      = State()
    filters  = State()

class ParserProxy(StatesGroup):
    input = State()
