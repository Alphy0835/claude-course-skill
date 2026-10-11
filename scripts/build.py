"""Проверка уроков и сборка курса в одну страницу.

    python build.py <папка курса>             проверить уроки и собрать course.html
    python build.py <папка курса> --check     только проверить, ничего не писать
    python build.py <папка курса> --artifact  ещё и course.artifact.html — вариант для публикации страницей

В папке курса лежат course.json (паспорт курса) и lessons/*.html (уроки-фрагменты).
Урок без файла считается ненаписанным: в программе он виден, но не открывается.
Ошибки останавливают сборку, замечания — нет. Зависимостей, кроме стандартной библиотеки, нет.
"""

import argparse
import base64
import html
import json
import math
import mimetypes
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template.html"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Скрипты, стили и встраивание чужих страниц в уроке запрещены: текст уроков пишется по материалам из сети.
FORBIDDEN = {"script", "style", "iframe", "object", "embed", "link", "meta", "base", "form", "input", "button"}
REQUIRED = [
    ("lead", "вводки <section class=\"lead\">"),
    ("check", "раздела «Проверь себя» <section class=\"check\">"),
    ("practice", "раздела «Практика» <section class=\"practice\">"),
    ("summary", "раздела «Главное» <section class=\"summary\">"),
    ("sources", "раздела «Источники» <section class=\"sources\">"),
]
WORDS_PER_MINUTE = 140  # учебный текст читают медленнее обычного
SHORT_LESSON = 1500     # слов; короче — повод проверить, раскрыты ли тезисы


class LessonCheck(HTMLParser):
    """Разбирает фрагмент урока: парность тегов, обязательные разделы, вопросы, термины, объём."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # открытые теги: (имя, строка, классы)
        self.errors = []
        self.warnings = []
        self.sections = set()
        self.quizzes = []
        self.terms = []
        self.words = 0
        self.source_links = 0
        self._quiz = None
        self._term = None

    def _inside(self, cls):
        return any(cls in classes for _, _, classes in self.stack)

    def _inspect(self, tag, attrs):
        line = self.getpos()[0]
        if tag in FORBIDDEN:
            self.errors.append(f"строка {line}: тег <{tag}> в уроке запрещён")
        if tag == "h1":
            self.errors.append(f"строка {line}: <h1> ставит сборщик, в уроке заголовки начинаются с <h2>")
        for name, value in attrs.items():
            if name.startswith("on"):
                self.errors.append(f"строка {line}: атрибут {name} запрещён")
            if name in ("href", "src") and (value or "").strip().lower().startswith("javascript:"):
                self.errors.append(f"строка {line}: ссылка с javascript: запрещена")
        if tag == "img" and re.match(r"(?i)https?:", attrs.get("src") or ""):
            self.errors.append(f"строка {line}: картинка из сети — положи файл в папку курса и сошлись на него")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        line = self.getpos()[0]
        self._inspect(tag, attrs)
        if tag == "section":
            self.sections |= classes
        if "quiz" in classes:
            self._quiz = {"line": line, "answer": attrs.get("data-answer"), "options": 0, "why": False,
                          "depth": len(self.stack)}
        elif self._quiz:
            if tag == "li" and len(self.stack) == self._quiz["depth"] + 2:
                self._quiz["options"] += 1
            if "why" in classes:
                self._quiz["why"] = True
        if tag == "dfn":
            self._term = {"line": line, "def": (attrs.get("data-def") or "").strip(), "text": []}
        if tag == "a" and self._inside("sources") and re.match(r"(?i)https?://", attrs.get("href") or ""):
            self.source_links += 1
        if tag not in VOID:
            self.stack.append((tag, line, classes))

    def handle_startendtag(self, tag, attrs):
        self._inspect(tag, dict(attrs))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        line = self.getpos()[0]
        if not self.stack:
            self.errors.append(f"строка {line}: лишний закрывающий </{tag}>")
            return
        if self.stack[-1][0] != tag:
            opened, at, _ = self.stack[-1]
            self.errors.append(f"строка {line}: закрыт </{tag}>, а открыт <{opened}> со строки {at}")
            if tag not in [name for name, _, _ in self.stack]:
                return
            while self.stack[-1][0] != tag:
                self.stack.pop()
        self.stack.pop()
        if self._quiz and len(self.stack) == self._quiz["depth"]:
            self.quizzes.append(self._quiz)
            self._quiz = None
        if tag == "dfn" and self._term:
            self._term["text"] = " ".join("".join(self._term["text"]).split())
            self.terms.append(self._term)
            self._term = None

    def handle_data(self, data):
        if self._term:
            self._term["text"].append(data)
        if not self._inside("sources"):
            self.words += len(re.findall(r"\w+", data))

    def finish(self):
        self.close()
        for name, line, _ in self.stack:
            self.errors.append(f"строка {line}: тег <{name}> не закрыт")
        for cls, label in REQUIRED:
            if cls not in self.sections:
                self.errors.append(f"нет {label}")
        if "check" in self.sections and len(self.quizzes) < 3:
            self.errors.append(f"вопросов в «Проверь себя»: {len(self.quizzes)}, нужно не меньше трёх")
        for quiz in self.quizzes:
            where = f"вопрос со строки {quiz['line']}"
            answer = quiz["answer"] or ""
            if not answer.isdigit() or not 1 <= int(answer) <= quiz["options"]:
                self.errors.append(f"{where}: data-answer=\"{answer}\" не указывает на вариант (вариантов {quiz['options']})")
            if not quiz["why"]:
                self.errors.append(f"{where}: нет объяснения <p class=\"why\">")
            if quiz["options"] < 3:
                self.warnings.append(f"{where}: вариантов меньше трёх")
        answers = {quiz["answer"] for quiz in self.quizzes}
        if len(self.quizzes) >= 4 and len(answers) == 1:
            self.warnings.append("правильный ответ во всех вопросах стоит на одном месте")
        for term in self.terms:
            if not term["def"]:
                self.warnings.append(f"строка {term['line']}: у термина «{term['text']}» нет data-def — в словарь не попадёт")
        if self.words < SHORT_LESSON:
            self.warnings.append(f"урок короткий ({self.words} слов) — проверь, что каждый тезис паспорта раскрыт с механизмом и примером")
        if "sources" in self.sections and not self.source_links:
            self.warnings.append("в «Источниках» нет ни одной ссылки")


def polish(fragment, course_dir):
    """Доводит фрагмент до вида страницы: рамки прокрутки, подсказки у терминов, картинки внутрь файла."""
    out = re.sub(r"<table\b", '<div class="scroll"><table', fragment).replace("</table>", "</table></div>")
    out = re.sub(r"<svg\b", '<div class="svg-wrap"><svg', out).replace("</svg>", "</svg></div>")
    out = re.sub(r'<dfn\b([^>]*?)\bdata-def="([^"]*)"', r'<dfn\1title="\2" data-def="\2"', out)

    def embed(match):
        tag = match.group(0)
        src = re.search(r'\bsrc="([^"]*)"', tag)
        if not src or src.group(1).startswith("data:"):
            return tag
        path = course_dir / src.group(1)
        if not path.is_file():
            raise FileNotFoundError(f"картинка не найдена: {src.group(1)}")
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        return tag.replace(src.group(0), f'src="data:{kind};base64,{payload}"')

    return re.sub(r"<img\b[^>]*>", embed, out)


def esc(text):
    return html.escape(str(text), quote=True)


def accent(title):
    """«Название с *акцентом*» — слова между звёздочками набираются курсивной антиквой."""
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc(title))


def plain(title):
    return str(title).replace("*", "")


def plural(n, forms):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def hours(minutes):
    value = round(minutes / 30) / 2
    return str(int(value)) if value == int(value) else str(value).replace(".", ",")


def hours_word(minutes):
    value = round(minutes / 30) / 2
    return plural(int(value), ("час", "часа", "часов")) if value == int(value) else "часа"


def main():
    parser = argparse.ArgumentParser(description="Проверка уроков и сборка курса в одну страницу")
    parser.add_argument("course", help="папка курса с course.json и lessons/")
    parser.add_argument("--check", action="store_true", help="только проверить")
    parser.add_argument("--artifact", action="store_true", help="дополнительно собрать вариант для публикации страницей")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    course_dir = Path(args.course).resolve()
    course = json.loads((course_dir / "course.json").read_text(encoding="utf-8"))
    slug = course.get("slug") or course_dir.name
    errors, warnings, report = [], [], []

    for field in ("title", "short", "level", "outcome", "modules"):
        if not course.get(field):
            errors.append(f"course.json: нет поля «{field}»")
    if errors:
        print("\n".join(errors))
        return 1

    lessons = []  # все уроки по порядку, с результатами проверки
    for m, module in enumerate(course["modules"], 1):
        for lesson in module["lessons"]:
            item = dict(lesson, module=m, module_title=module["title"], written=False,
                        words=0, quizzes=0, terms=[], body="", practice=int(lesson.get("practice_min") or 0))
            path = course_dir / lesson["file"] if lesson.get("file") else None
            if path and path.is_file():
                raw = path.read_text(encoding="utf-8")
                check = LessonCheck()
                check.feed(raw)
                check.finish()
                errors += [f"урок {lesson['id']} ({lesson['file']}): {e}" for e in check.errors]
                warnings += [f"урок {lesson['id']}: {w}" for w in check.warnings]
                try:
                    body = polish(raw, course_dir)
                except FileNotFoundError as problem:
                    errors.append(f"урок {lesson['id']}: {problem}")
                    body = ""
                item.update(written=True, words=check.words, quizzes=len(check.quizzes), body=body,
                            terms=[t for t in check.terms if t["def"]],
                            read=max(5, math.ceil(check.words / WORDS_PER_MINUTE / 5) * 5))
                report.append(f"  {lesson['id']}  {check.words:>5} слов  ~{item['read']:>3} мин чтения  "
                              f"вопросов {len(check.quizzes)}  терминов {len(item['terms'])}  {lesson['title']}")
            else:
                report.append(f"  {lesson['id']}  — не написан —  {lesson['title']}")
            lessons.append(item)

    seen = set()
    for item in lessons:
        if item["id"] in seen:
            errors.append(f"course.json: номер урока {item['id']} повторяется")
        seen.add(item["id"])

    written = [item for item in lessons if item["written"]]
    total_min = sum(item["read"] + item["practice"] for item in written)
    print(f"Курс «{plain(course['title'])}», уровень: {course['level']}")
    print("\n".join(report))
    print(f"Написано уроков: {len(written)} из {len(lessons)} · слов {sum(i['words'] for i in written)} · "
          f"вопросов {sum(i['quizzes'] for i in written)} · около {hours(total_min)} ч с практикой")
    if warnings:
        print("\nЗамечания:\n" + "\n".join("  " + w for w in warnings))
    if errors:
        print("\nОшибки (сборка остановлена):\n" + "\n".join("  " + e for e in errors))
        return 1
    if args.check:
        return 0

    # --- рейка с программой ---
    rail = ['<p class="hud">Программа · <span data-count></span></p>', '<ol class="rail-mods">']
    for m, module in enumerate(course["modules"], 1):
        rail.append(f'<li><span class="rail-mod">Модуль {m}. {esc(module["title"])}</span><ol>')
        for item in (i for i in lessons if i["module"] == m):
            label = f'<span class="n">{esc(item["id"])}</span><span class="t">{esc(item["title"])}</span>'
            if item["written"]:
                rail.append(f'<li data-lesson="{esc(item["id"])}"><a href="#l-{esc(item["id"])}" '
                            f'data-nav="l-{esc(item["id"])}">{label}</a></li>')
            else:
                rail.append(f"<li>{label}</li>")
        rail.append("</ol></li>")
    rail.append("</ol>")
    rail.append('<div class="rail-extra"><a href="#home" data-nav="home">О курсе</a>'
                '<a href="#trainer" data-nav="trainer">Тренажёр</a>'
                '<a href="#glossary" data-nav="glossary">Словарь</a></div>')

    # --- первая страница ---
    glossary = sorted(((t["text"], t["def"], item["id"]) for item in written for t in item["terms"]),
                      key=lambda row: row[0].casefold())
    pending = len(lessons) - len(written)
    hud = f'Курс · уровень: {esc(course["level"])}'
    if course.get("facts_date"):
        hud += f' · факты на {esc(course["facts_date"])}'
    home = [f'<section class="view home" id="home"><p class="hud">{hud}</p>',
            f'<h1 class="title">{accent(course["title"])}</h1>']
    if course.get("subtitle"):
        home.append(f'<p class="lede">{esc(course["subtitle"])}</p>')
    stats = [(len(lessons), plural(len(lessons), ("урок", "урока", "уроков"))),
             (hours(total_min), hours_word(total_min) + " с практикой" + (" — написанные уроки" if pending else "")),
             (sum(i["quizzes"] for i in written), "вопросов для проверки"),
             (len(glossary), plural(len(glossary), ("термин", "термина", "терминов")) + " в словаре")]
    home.append('<dl class="stats">' + "".join(f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"
                                               for value, label in stats) + "</dl>")
    if written:
        home.append(f'<a class="cta" id="resume" href="#l-{esc(written[0]["id"])}">Начать с урока {esc(written[0]["id"])}</a>')
    home.append('<h2>Что ты сможешь после курса</h2><ol class="outcome">'
                + "".join(f"<li>{esc(line)}</li>" for line in course["outcome"]) + "</ol>")
    home.append('<h2>Программа</h2><ol class="program">')
    for m, module in enumerate(course["modules"], 1):
        home.append(f'<li><div class="mod-head"><span class="mod-n">{m}</span><div><h3>{esc(module["title"])}</h3>'
                    + (f'<p>{esc(module["goal"])}</p>' if module.get("goal") else "") + '</div></div><ol class="rows">')
        for item in (i for i in lessons if i["module"] == m):
            if item["written"]:
                time = f'{item["read"]} мин' + (f' + {item["practice"]} практика' if item["practice"] else "")
                home.append(f'<li data-lesson="{esc(item["id"])}"><a href="#l-{esc(item["id"])}">'
                            f'<span class="n">{esc(item["id"])}</span><span class="t">{esc(item["title"])}</span>'
                            f'<span class="m">{time}</span></a></li>')
            else:
                home.append(f'<li><span class="row"><span class="n">{esc(item["id"])}</span>'
                            f'<span class="t">{esc(item["title"])}</span><span class="m">готовится</span></span></li>')
        home.append("</ol></li>")
    home.append("</ol>")
    if course.get("reader"):
        home.append(f'<h2>Для кого написано</h2><p class="fine">{esc(course["reader"])}</p>')
    if course.get("out_of_scope"):
        home.append('<div class="fine">За рамками курса:<ul>'
                    + "".join(f"<li>{esc(line)}</li>" for line in course["out_of_scope"]) + "</ul></div>")
    if course.get("facts_date"):
        home.append(f'<p class="fine">Факты сверены на {esc(course["facts_date"])}. Названия, версии и цены '
                    "стареют первыми — рядом с ними в уроках стоит дата.</p>")
    home.append("</section>")

    # --- уроки ---
    articles = []
    for at, item in enumerate(written):
        number = lessons.index(item) + 1
        hud = (f'Модуль {item["module"]} · урок {number} из {len(lessons)} · {item["read"]} мин чтения'
               + (f' · {item["practice"]} мин практики' if item["practice"] else ""))
        pager = []
        if at:
            pager.append(f'<a href="#l-{esc(written[at - 1]["id"])}">← Урок {esc(written[at - 1]["id"])}</a>')
        if at + 1 < len(written):
            pager.append(f'<a href="#l-{esc(written[at + 1]["id"])}">Урок {esc(written[at + 1]["id"])} →</a>')
        else:
            pager.append('<a href="#trainer">Проверка по всему курсу →</a>')
        articles.append(
            f'<article class="view lesson" id="l-{esc(item["id"])}" data-id="{esc(item["id"])}" '
            f'data-title="{esc(item["title"])}" hidden>'
            f'<header class="lesson-head"><p class="hud">{hud}</p><h1>{esc(item["title"])}</h1>'
            + (f'<p class="goal">{esc(item["goal"])}</p>' if item.get("goal") else "")
            + f'</header><div class="prose">\n{item["body"]}\n</div>'
            f'<footer class="lesson-foot"><button type="button" class="btn" data-done="{esc(item["id"])}">'
            f'Отметить пройденным</button><nav class="pager">{"".join(pager)}</nav></footer></article>')

    # --- словарь ---
    gloss = [f'<section class="view" id="glossary" hidden><p class="hud">Словарь · {len(glossary)} '
             f'{plural(len(glossary), ("термин", "термина", "терминов"))}</p><h1 class="h-view">Словарь курса</h1>']
    if glossary:
        gloss.append('<dl class="gloss">' + "".join(
            f'<div><dt>{esc(term)}</dt><dd>{esc(meaning)} <a href="#l-{esc(lesson)}">урок {esc(lesson)}</a></dd></div>'
            for term, meaning, lesson in glossary) + "</dl>")
    else:
        gloss.append('<p class="fine">Термины появятся здесь, когда будут написаны уроки.</p>')
    gloss.append("</section>")

    data = json.dumps({"slug": slug, "lessons": [{"id": i["id"], "title": i["title"]} for i in written]},
                      ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    for mark, value in (("<!--@SHORT-->", esc(course["short"])), ("<!--@RAIL-->", "\n".join(rail)),
                        ("<!--@HOME-->", "\n".join(home)), ("<!--@LESSONS-->", "\n".join(articles)),
                        ("<!--@GLOSSARY-->", "\n".join(gloss)), ("<!--@DATA-->", data)):
        page = page.replace(mark, value)
    head, body = page.split("<!--@BODY-->")

    full = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + head + "</head>\n<body>" + body + "</body>\n</html>\n")
    (course_dir / "course.html").write_text(full, encoding="utf-8")
    print(f"\nСобрано: {course_dir / 'course.html'}")
    if args.artifact:
        # Площадка страниц сама оборачивает файл в документ, поэтому здесь только содержимое.
        (course_dir / "course.artifact.html").write_text(head + body, encoding="utf-8")
        print(f"Для публикации: {course_dir / 'course.artifact.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
