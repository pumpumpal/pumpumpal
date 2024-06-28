token: str = "MTI0NzU5MjQ4MDgwNzk4MTA5Ng.Go1j6f.UPY19tvz5GlqZKs1h5PyP_Sl6Y2BVeX37IUsx4"
# DEV - "MTI0NzU5MjQ4MDgwNzk4MTA5Ng.Go1j6f.UPY19tvz5GlqZKs1h5PyP_Sl6Y2BVeX37IUsx4"
# MAIN - "MTI0NzQ5OTUzMjk1MDk2NjMxMw.G0EwjV.nqtX8DZGa1Iq7A_l9igV0MphSoCCANhLMg4Rsg"

prefix: str = ","
owners: list[int] = [1183542863578013788, 213743026026184704]


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
    host: str = "127.0.0.1"
    port: int = 5432
    name: str = "sexytea69"
    user: str = "postgres"
    password: str = "cafesitos69"


class Webserver:
    host: str = "0.0.0.0"
    port: int = 59076


class Authorization:
    class Spotify:
        client_id: str = "7a4483c9ae964b8f946ccf4c56d5af25"
        client_secret: str = "28a9f7417338469e83607aae36ce73fc"

    removebg: str = "gypCjW9B2UwdLwZtJ6tPcoYY"
    weather: str = "gypCjW9B2UwdLwZtJ6tPcoYY"
