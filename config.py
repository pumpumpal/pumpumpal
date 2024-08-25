token: str = "MTI0NzQ5OTUzMjk1MDk2NjMxMw.GaX3yZ.vNLjqonr9ok3rbCobjJ2ieBM4S_OnbZ8Job9xA"
# DEV - "MTI0NzU5MjQ4MDgwNzk4MTA5Ng.GB1DXW.wxoc1J0r5-J6FTfSs1AIUQYJqtjlQ3Gt5yFmtk"
# MAIN - "MTI0NzQ5OTUzMjk1MDk2NjMxMw.GaX3yZ.vNLjqonr9ok3rbCobjJ2ieBM4S_OnbZ8Job9xA"

prefix: str = ","
owners: list[int] = [1183542863578013788, 213743026026184704, 1208459597552156774]


class Color:
    neutral: int = 0x2B2D31
    approval: int = 0xA9E97A
    error: int = 0xFFCC00


class Emoji:
    class Paginator:
        navigate: str = "<:nav:1247534695936163840>"
        previous: str = "<:next:1247534692836577311> "
        _next: str = "<:prev:1247534694233276457>"
        cancel: str = "<:cancel:1247534691376959530>"

    class Interface:
        lock: str = "<:lock:1247534690278051840>"
        unlock: str = "<:unlock:1247534688415776950>"
        ghost: str = "<:ghost:1247534687035985931>"
        reveal: str = "<:reveal:1247535372813205596>"
        claim: str = "<:claim:1247534713321689139>"
        disconnect: str = "<:disconnect:1247535369877061654>"
        activity: str = "<:activity:1247534709433565286>"
        information: str = "<:info:1247535367435845745>"
        increase: str = "<:increase:1247534697299579004>"
        decrease: str = "<:decrease:1247534705407168592>"

    approve: str = "<:approve:1247535365632557066>"
    warn: str = "<:warn:1247534701191626782>"
    deny: str = "<:deny:1247534699295805562>"


class Database:
    host: str = "postgres.pumpumpal.local"
    port: int = 5432
    name: str = "pumpumpal"
    user: str = "blez"
    password: str = "n5d3M9SzK0WYE28"


class Webserver:
    host: str = "0.0.0.0"
    port: int = 59076


class Authorization:
    class Spotify:
        client_id: str = "7a4483c9ae964b8f946ccf4c56d5af25"
        client_secret: str = "28a9f7417338469e83607aae36ce73fc"

    removebg: str = "gypCjW9B2UwdLwZtJ6tPcoYY"
    weather: str = "gypCjW9B2UwdLwZtJ6tPcoYY"
