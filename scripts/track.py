"""Страница профессии и общий словарь.

    python track.py <папка профессии>

В папке лежит track.json — паспорт профессии со списком курсов по порядку. Каждый курс —
обычная папка курса внутри неё. Сценарий смотрит, в каком состоянии каждый курс, собирает
index.html со списком курсов и glossary.md — общий словарь из написанных уроков —
и называет курс, который делать следующим. Зависимостей, кроме стандартной библиотеки, нет.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import TEMPLATE, LessonCheck, accent, esc, plain, plural  # noqa: E402

# Страница профессии берёт цвета и шрифты у страницы курса; здесь только то, чего там нет.
STYLE = """<style>
main.solo .view{margin-inline:auto}
.courses{list-style:none;margin:28px 0 0;padding:0}
.courses>li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:20px;padding:26px 0;border-top:1px solid var(--line)}
.courses .mod-n{min-width:1.4em}
.courses>li>div{display:grid;gap:8px;align-content:start}
.courses h3{margin:0;font-family:var(--f-display);font-weight:400;font-size:21px;line-height:1.25;color:var(--fg-2)}
.courses h3 a{color:var(--fg);text-decoration:none}
.courses h3 a:hover{color:var(--accent)}
.courses p{margin:0;font-family:var(--f-display);font-weight:300;font-size:15px;line-height:1.5;color:var(--fg-2)}
.courses .meta{display:flex;flex-wrap:wrap;gap:4px 18px;font-family:var(--f-mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--fg-3)}
.courses .meta .core{color:var(--accent)}
.courses .is-ready .state,.courses [data-progress]{color:var(--good)}
.courses .is-open .mod-n{color:var(--fg)}
</style>
"""

SCRIPT = """<script>
(function () {
  var root = document.documentElement, btn = document.getElementById('themeBtn');
  var KEY = 'track:' + root.getAttribute('data-track') + ':theme';
  // Хранилище браузера бывает недоступно — страница обязана работать и без него.
  try { var saved = localStorage.getItem(KEY); if (saved) root.setAttribute('data-theme', saved); } catch (e) {}
  function paint() { btn.textContent = root.getAttribute('data-theme') === 'light' ? 'Тёмная' : 'Светлая'; }
  btn.addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    paint();
  });
  paint();
  // Пройденные уроки запоминает страница курса. Отсюда они видны не в каждом браузере — тогда строка просто пустая.
  Array.prototype.forEach.call(document.querySelectorAll('[data-slug]'), function (row) {
    try {
      var done = JSON.parse(localStorage.getItem('course:' + row.getAttribute('data-slug') + ':done') || '[]');
      if (done.length) row.querySelector('[data-progress]').textContent =
        'пройдено ' + done.length + ' из ' + row.getAttribute('data-lessons');
    } catch (e) {}
  });
})();
</script>
"""


def course_state(track_dir, entry):
    """Состояние курса по его папке: сколько уроков задумано и написано, собрана ли страница, какие термины введены."""
    folder = track_dir / entry["dir"]
    state = {"lessons": 0, "written": 0, "page": (folder / "course.html").is_file(), "slug": entry["dir"], "terms": []}
    passport = folder / "course.json"
    if not passport.is_file():
        return state
    course = json.loads(passport.read_text(encoding="utf-8"))
    state["slug"] = course.get("slug") or folder.name
    for module in course.get("modules", []):
        for lesson in module.get("lessons", []):
            state["lessons"] += 1
            path = folder / lesson["file"] if lesson.get("file") else None
            if path and path.is_file():
                state["written"] += 1
                check = LessonCheck()
                check.feed(path.read_text(encoding="utf-8"))
                state["terms"] += [(t["text"], t["def"], lesson["id"]) for t in check.terms if t["def"]]
    return state


def status(state):
    """Код состояния для вёрстки и подпись для человека."""
    if not state["lessons"]:
        return "pending", "не начат"
    count = f'{state["lessons"]} {plural(state["lessons"], ("урок", "урока", "уроков"))}'
    if not state["written"]:
        return "planned", f"программа готова · {count}"
    if state["written"] < state["lessons"]:
        return "partial", f'написано {state["written"]} из {state["lessons"]}'
    if not state["page"]:
        return "partial", f"уроки написаны, страница не собрана · {count}"
    return "ready", f"готов · {count}"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    track_dir = Path(sys.argv[1]).resolve()
    track = json.loads((track_dir / "track.json").read_text(encoding="utf-8"))

    errors = [f"track.json: нет поля «{field}»" for field in ("title", "short", "level", "outcome", "courses")
              if not track.get(field)]
    earlier = set()
    for entry in track.get("courses", []):
        missing = [field for field in ("id", "dir", "title", "graduate") if not entry.get(field)]
        if missing:
            errors.append(f"track.json: у курса {entry.get('id', '?')} нет полей: {', '.join(missing)}")
            continue
        if Path(entry["dir"]).name != entry["dir"]:
            errors.append(f"track.json: папка курса {entry['id']} должна быть простым именем, без пути")
        if entry["id"] in earlier:
            errors.append(f"track.json: номер курса {entry['id']} повторяется")
        # Лестница: опираться можно только на курсы, которые идут раньше.
        for need in entry.get("needs", []):
            if need not in earlier:
                errors.append(f"track.json: курс {entry['id']} опирается на курс {need}, которого нет раньше по списку")
        earlier.add(entry["id"])
    if errors:
        print("Ошибки (сборка остановлена):\n" + "\n".join("  " + e for e in errors))
        return 1

    rows, report, glossary, next_up = [], [], [], None
    ready = lessons_written = terms_total = 0
    first_open = None
    for entry in track["courses"]:
        state = course_state(track_dir, entry)
        code, label = status(state)
        ready += code == "ready"
        lessons_written += state["written"]
        terms_total += len(state["terms"])
        if code != "ready" and next_up is None:
            next_up = entry
        report.append(f'  {entry["id"]}  {label:<34}  {entry["title"]}')
        if state["terms"]:
            glossary += [f'## {entry["id"]} · {entry["title"]}', ""]
            glossary += [f"- **{term}** — {meaning} (урок {lesson})" for term, meaning, lesson in state["terms"]]
            glossary.append("")

        link = f'{entry["dir"]}/course.html' if state["page"] else None
        if link and first_open is None:
            first_open = (entry, link)
        title = f'<a href="{esc(link)}">{esc(entry["title"])}</a>' if link else esc(entry["title"])
        meta = []
        if entry.get("mark"):
            meta.append(f'<span class="{"core" if entry["mark"] == "ядро" else "grow"}">{esc(entry["mark"])}</span>')
        if entry.get("needs"):
            meta.append(f'<span>опирается на {esc(", ".join(entry["needs"]))}</span>')
        meta.append(f'<span class="state">{esc(label)}</span><span data-progress></span>')
        classes = " ".join(c for c in (f"is-{code}", "is-open" if link else "") if c)
        rows.append(
            f'<li class="{classes}" data-slug="{esc(state["slug"])}" data-lessons="{state["lessons"]}">'
            f'<span class="mod-n">{esc(entry["id"])}</span><div><h3>{title}</h3>'
            f'<p>{esc(entry["graduate"])}</p><p class="meta">{"".join(meta)}</p>'
            + (f'<p>В портфолио: {esc(entry["portfolio"])}</p>' if entry.get("portfolio") else "")
            + "</div></li>")

    total = len(track["courses"])
    print(f"Профессия «{plain(track['title'])}», уровень: {track['level']}")
    print("\n".join(report))
    print(f"Готово курсов: {ready} из {total} · уроков написано {lessons_written} · терминов в общем словаре {terms_total}")
    print(f'Следующий курс: {next_up["id"]} · {next_up["title"]} (папка {next_up["dir"]})' if next_up
          else "Все курсы готовы.")

    head = [f"# Общий словарь: {plain(track['title'])}", "",
            "Собирается сценарием track.py из написанных уроков. Руками не править: правки сотрутся при следующей сборке.", ""]
    (track_dir / "glossary.md").write_text(
        "\n".join(head + (glossary or ["Пока пусто: термины появятся после первого написанного урока.", ""])),
        encoding="utf-8")

    hud = f'Профессия · уровень: {esc(track["level"])}'
    if track.get("facts_date"):
        hud += f' · факты на {esc(track["facts_date"])}'
    view = [f'<section class="view home"><p class="hud">{hud}</p>', f'<h1 class="title">{accent(track["title"])}</h1>']
    if track.get("subtitle"):
        view.append(f'<p class="lede">{esc(track["subtitle"])}</p>')
    stats = [(total, plural(total, ("курс", "курса", "курсов"))), (ready, "готово"),
             (lessons_written, plural(lessons_written, ("урок написан", "урока написано", "уроков написано"))),
             (terms_total, plural(terms_total, ("термин", "термина", "терминов")) + " в общем словаре")]
    view.append('<dl class="stats">' + "".join(f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"
                                               for value, label in stats) + "</dl>")
    if first_open:
        view.append(f'<a class="cta" href="{esc(first_open[1])}">Открыть курс {esc(first_open[0]["id"])}</a>')
    view.append('<h2>Что ты будешь делать сам</h2><ol class="outcome">'
                + "".join(f"<li>{esc(line)}</li>" for line in track["outcome"]) + "</ol>")
    view.append('<h2>Курсы по порядку</h2><ol class="courses">' + "\n".join(rows) + "</ol>")
    if track.get("grade"):
        view.append(f'<h2>До какой ступени</h2><p class="fine">{esc(track["grade"])}</p>')
    if track.get("reader"):
        view.append(f'<h2>Для кого написано</h2><p class="fine">{esc(track["reader"])}</p>')
    if track.get("out_of_scope"):
        view.append('<div class="fine">За рамками:<ul>'
                    + "".join(f"<li>{esc(line)}</li>" for line in track["out_of_scope"]) + "</ul></div>")
    view.append("</section>")

    head_html = TEMPLATE.read_text(encoding="utf-8").split("<!--@BODY-->")[0].replace("<!--@SHORT-->", esc(track["short"]))
    page = ('<!doctype html>\n<html lang="ru" data-track="' + esc(track_dir.name) + '">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + head_html + STYLE + "</head>\n<body>\n"
            f'<header class="top"><span class="brand">{esc(track["short"])}</span>'
            f'<span class="count">{ready} из {total}</span>'
            '<button type="button" id="themeBtn">Светлая</button></header>\n'
            '<main class="solo">\n' + "\n".join(view) + "\n</main>\n" + SCRIPT + "</body>\n</html>\n")
    (track_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"\nСобрано: {track_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
