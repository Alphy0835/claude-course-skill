"""Снимки урока в браузере без окна — чтобы посмотреть вёрстку глазами.

Запуск:
    python shots.py <папка курса> <id урока> [--out <папка>] [--chrome <путь к браузеру>]

Снимает первую страницу курса, начало урока, каждую схему, первые две таблицы,
вопросы и практику на большом (1440) и узком (500) экране в тёмной теме
и начало урока в светлой.
Сначала собери курс: снимки делаются с course.html.

Прокрутка в браузере без окна даёт пустой снимок, поэтому страница не прокручивается,
а сдвигается вверх отрицательным отступом так, чтобы нужный блок оказался под шапкой.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

SCRIPT = """
<script>
window.addEventListener('load', function () {
  location.hash = '#l-%(lesson)s';
  setTimeout(function () {
    if (%(light)s) document.documentElement.setAttribute('data-theme', 'light');
    var view = document.getElementById('l-%(lesson)s');
    if (!view) return;
    view.querySelectorAll('details').forEach(function (d) { d.open = true; });
    window.dispatchEvent(new Event('resize'));
    var el = view.querySelectorAll(%(selector)s)[%(index)d];
    window.scrollTo(0, 0);
    if (el) {
      var y = el.getBoundingClientRect().top - 70;
      if (y > 0) view.style.marginTop = (-y) + 'px';
    }
  }, 400);
});
</script>
"""


def find_browser(given):
    if given:
        return given
    for path in BROWSERS:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Не нашёл Chrome или Edge. Укажи путь: --chrome <путь>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("course")
    ap.add_argument("lesson")
    ap.add_argument("--out")
    ap.add_argument("--chrome")
    args = ap.parse_args()

    course = Path(args.course).resolve()
    page = course / "course.html"
    if not page.exists():
        sys.exit(f"Нет {page}: сначала собери курс (build.py)")
    html = page.read_text(encoding="utf-8")

    meta = json.loads((course / "course.json").read_text(encoding="utf-8"))
    lesson = next((l for m in meta["modules"] for l in m["lessons"] if l["id"] == args.lesson), None)
    if not lesson or not (course / lesson["file"]).exists():
        sys.exit(f"Урок {args.lesson} не написан или его нет в course.json")
    fragment = (course / lesson["file"]).read_text(encoding="utf-8")

    targets = [("top", ".lesson-head", 0)]
    targets += [(f"fig{i + 1}", "figure", i) for i in range(fragment.count("<figure"))]
    targets += [(f"table{i + 1}", ".prose table", i) for i in range(min(2, fragment.count("<table")))]
    targets += [("check", "section.check", 0), ("practice", "section.practice", 0)]

    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "course-shots" / f"{course.name}-{args.lesson}"
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    browser = find_browser(args.chrome)

    # Первая страница открывается сама, сдвигать нечего: у неё нет селектора.
    shots = [("home", None, 0, False, width) for width in (1440, 500)]
    shots += [(name, sel, idx, False, width) for name, sel, idx in targets for width in (1440, 500)]
    shots.append(("top", ".lesson-head", 0, True, 1440))

    for name, sel, idx, light, width in shots:
        stem = f"{name}-{'light' if light else 'dark'}-{width}"
        src = pages / f"{stem}.html"
        if sel is None:
            src.write_text(html, encoding="utf-8")
        else:
            script = SCRIPT % {
                "lesson": args.lesson,
                "light": "true" if light else "false",
                "selector": json.dumps(sel),
                "index": idx,
            }
            src.write_text(html.replace("</body>", script + "</body>"), encoding="utf-8")
        png = out / f"{stem}.png"
        subprocess.run(
            [browser, "--headless=new", "--hide-scrollbars", "--disable-gpu",
             f"--window-size={width},1100", "--virtual-time-budget=6000",
             f"--screenshot={png}", src.as_uri()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
        )
        print(("готово  " if png.exists() else "НЕ СНЯТО  ") + str(png))

    shutil.rmtree(pages, ignore_errors=True)


if __name__ == "__main__":
    main()
