from aiogram.fsm.state import State, StatesGroup


class Purchase(StatesGroup):
    waiting_recipient = State()


class TopUp(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class Appeal(StatesGroup):
    waiting_message = State()


class AdminSettings(StatesGroup):
    waiting_currency = State()
    waiting_referral_percent = State()
    waiting_stars_prices = State()
    waiting_premium_prices = State()
    waiting_card_number = State()
    waiting_card_holder = State()
    waiting_add_admin = State()


class AdminChannel(StatesGroup):
    waiting_add = State()


class AdminBroadcast(StatesGroup):
    waiting_message = State()


class AdminUserManage(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


class AdminEmoji(StatesGroup):
    waiting_value = State()
    waiting_bulk = State()


class AdminCoinDrop(StatesGroup):
    waiting_key = State()
    waiting_markup = State()
    waiting_rate = State()
