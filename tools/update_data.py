#!/usr/bin/env python3
"""
Обновление data.js для страницы «Команда сейчас» по данным сайта РФБ.

Запуск:
  python3 tools/update_data.py                 -- скачать страницы с competitions.russiabasket.ru
  python3 tools/update_data.py --files таблица.html суперлига.html кубок.html
                                               -- разобрать сохранённые страницы
                                                  (по порядку: положение Суперлиги, матчи Суперлиги, матчи Кубка)

Нужен только Python 3, дополнительные библиотеки не требуются.
Если с данными что-то не так (пустая страница, изменилась вёрстка), файл data.js НЕ перезаписывается.
"""
import html as htmllib
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://competitions.russiabasket.ru"
URL_TABLE = BASE + "/superliga/men/polozhenie/"
URL_SL_GAMES = BASE + "/superliga/men/games/"
URL_CUP_GAMES = BASE + "/russia-cup/men/games/"

YUGRA_ID = "760"
SEASON = "2026/27"
# Названия этапов кубка по порядку. РФБ на странице матчей их не пишет, поэтому названия заданы здесь.
ROUND_NAMES = ["1/16 финала", "1/8 финала", "1/4 финала", "1/2 финала", "Финал"]

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
MSK = timezone(timedelta(hours=3))
OUT = Path(__file__).resolve().parent.parent / "data.js"


def fetch(url):
    # представляемся нейтрально, без личных данных
    req = urllib.request.Request(url, headers={"User-Agent": "school-project-site/1.0", "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s))).strip()


def team_names(page):
    """id команды -> (название, город) из выпадающего списка «Все команды»."""
    out = {}
    for tid, full in re.findall(r'data-val="(\d+)"\s+data-category="team"[^>]*>([^<]+)<', page):
        if tid == "0":
            continue
        full = clean(full)
        m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", full)
        out[tid] = (m.group(1), m.group(2)) if m else (full, "")
    return out


def display_names(names):
    """Короткое название; если названия повторяются (два «Динамо»), добавляем город."""
    count = {}
    for n, _ in names.values():
        count[n] = count.get(n, 0) + 1
    return {tid: (n if count[n] == 1 or not c else f"{n} ({c})") for tid, (n, c) in names.items()}


def parse_games(page):
    """Все матчи страницы: список словарей. Первая команда в записи всегда хозяин."""
    games = []
    for chunk in page.split('<div class="matches-table__item _game')[1:]:
        head = chunk[:chunk.index(">")]
        ids = re.findall(r"_team(\d+)", head)
        status = re.search(r"_status(\d)", head)
        d = re.search(r"<p>\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})(?:,\s*(\d{1,2}:\d{2}))?", chunk)   # время у будущих матчей бывает не указано
        if len(ids) != 2 or not status or not d or d.group(2) not in MONTHS:
            raise ValueError("Не удалось разобрать матч, возможно, изменилась вёрстка сайта: " + head[:80])
        scores = re.findall(r'match-opponent__result[^"]*">\s*(\d+)\s*<', chunk)[:2]
        dt = datetime(int(d.group(3)), MONTHS[d.group(2)], int(d.group(1)),
                      *(map(int, d.group(4).split(":")) if d.group(4) else (0, 0)))
        games.append({
            "home": ids[0], "away": ids[1], "dt": dt, "time": d.group(4) or "",
            "finished": status.group(1) == "2" and len(scores) == 2,
            "score": f"{scores[0]}:{scores[1]}" if len(scores) == 2 else None,
        })
    return sorted(games, key=lambda g: g["dt"])


def fmt_date(dt):
    return dt.strftime("%d.%m.%Y")


def parse_table(page, disp):
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) != 11:
            continue
        link = re.search(r"team/\?id=(\d+)", tds[1])
        name = disp.get(link.group(1)) if link else None
        if not name:
            name = clean(tds[1])
        rows.append([name, clean(tds[2]), clean(tds[3]), clean(tds[4]), clean(tds[5]),
                     clean(tds[7]), clean(tds[8]), clean(tds[9]), clean(tds[10])])
    return rows


def build_superliga(table_page, games_page):
    names = team_names(games_page)
    disp = display_names(names)
    table = parse_table(table_page, disp)
    mine = [g for g in parse_games(games_page) if YUGRA_ID in (g["home"], g["away"])]
    schedule = [[fmt_date(g["dt"]), g["time"], disp[g["home"]], disp[g["away"]]]
                for g in mine if not g["finished"]]
    results = [[fmt_date(g["dt"]), disp[g["home"]], disp[g["away"]], g["score"]]
               for g in mine if g["finished"]]
    return {"source": BASE + "/superliga/men/", "table": table, "schedule": schedule, "results": results}


def build_cup(cup_page):
    disp = display_names(team_names(cup_page))
    games = parse_games(cup_page)
    pairs = {}
    for g in games:                      # пара = две команды, независимо от того, кто хозяин
        pairs.setdefault(frozenset((g["home"], g["away"])), []).append(g)
    ties = sorted(pairs.values(), key=lambda legs: legs[0]["dt"])
    rounds, cur, cur_end = [], [], None
    for legs in ties:                    # новый этап начинается, когда прошли все ответные матчи предыдущего
        if cur and legs[0]["dt"] > cur_end:
            rounds.append(cur)
            cur, cur_end = [], None
        cur.append(legs)
        last = legs[-1]["dt"]
        cur_end = last if cur_end is None or last > cur_end else cur_end
    if cur:
        rounds.append(cur)
    out = []
    for i, r in enumerate(rounds):
        out.append({"name": ROUND_NAMES[i] if i < len(ROUND_NAMES) else f"Этап {i + 1}",
                    "ties": [{"legs": [dict(
                        date=fmt_date(g["dt"]),
                        **({} if g["finished"] or not g["time"] else {"time": g["time"]}),
                        home=disp[g["home"]], away=disp[g["away"]], score=g["score"] if g["finished"] else None)
                        for g in legs]} for legs in r]})
    for name in ROUND_NAMES[len(rounds):]:      # будущие этапы: пока пустые
        out.append({"name": name, "ties": []})
    return {"source": BASE + "/russia-cup/men/", "rounds": out}


def check(data):
    sl, cup = data["superliga"], data["cup"]
    problems = []
    if len(sl["table"]) < 8:
        problems.append("в таблице Суперлиги слишком мало команд")
    if not (sl["schedule"] or sl["results"]):
        problems.append("нет матчей «Югры» в Суперлиге")
    if not cup["rounds"][0]["ties"]:
        problems.append("в кубке не найдено ни одной пары")
    for t in sl["table"]:
        if len(t) != 9 or not t[1].isdigit():
            problems.append("строка таблицы разобрана неверно: " + str(t))
            break
    return problems


def main(argv):
    if "--files" in argv:
        a = argv[argv.index("--files") + 1:]
        if len(a) != 3:
            sys.exit("Нужно три файла: положение Суперлиги, матчи Суперлиги, матчи Кубка")
        table_p, sl_p, cup_p = (Path(x).read_text(encoding="utf-8") for x in a)
    else:
        table_p, sl_p, cup_p = fetch(URL_TABLE), fetch(URL_SL_GAMES), fetch(URL_CUP_GAMES)
    data = {"season": SEASON,
            "updated": datetime.now(MSK).strftime("%d.%m.%Y, %H:%M (МСК)"),
            "superliga": build_superliga(table_p, sl_p),
            "cup": build_cup(cup_p)}
    problems = check(data)
    if problems:
        sys.exit("data.js не изменён. Проблемы: " + "; ".join(problems))
    # если данные не изменились, файл не трогаем (иначе сайт перевыкладывался бы без нужды каждые 30 минут)
    if OUT.exists():
        try:
            txt = OUT.read_text(encoding="utf-8")
            old_data = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
            if {k: v for k, v in old_data.items() if k != "updated"} == {k: v for k, v in data.items() if k != "updated"}:
                print("Данные не изменились, data.js не тронут.")
                return
        except (ValueError, KeyError):
            pass
    body = json.dumps(data, ensure_ascii=False, indent=1)
    OUT.write_text("// Файл создаётся автоматически скриптом tools/update_data.py. Вручную лучше не править.\n"
                   "window.YUGRA_DATA = " + body + ";\n", encoding="utf-8")
    print("data.js обновлён:", data["updated"])


if __name__ == "__main__":
    main(sys.argv[1:])
