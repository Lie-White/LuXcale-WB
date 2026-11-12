# LuXcale-WB

> **Beta.** LuXcale-WB is being tested. Check its results yourself, and please tell us what breaks
> or what is awkward: see [Feedback](#feedback). It has been checked on Amersham chemiluminescence
> TIFFs so far; reports from other imagers are especially welcome.
>
> **베타 버전입니다.** 결과는 직접 확인하고 쓰시고, 문제나 불편한 점을 [피드백](#feedback)으로 알려 주세요.
> 지금까지 Amersham 이미저의 화학발광 TIFF로 검증했고, 다른 이미저(ChemiDoc 등) 사용 후기를 특히 환영합니다.

Western blot band quantification from the imager's raw 16-bit chemiluminescence TIFF,
from the raw image to a normalised result, a graph and a publication figure. Windows.

The screen contrast only changes what you see. Numbers always come from the raw image.

## ⬇️ Download

**[Go to the latest version](../../releases/latest)**

1. Click the link above, or click **Releases** on the right side of this page and open the newest one (marked **Latest**).
2. Under **Assets**, click **`LuXcale-WB-<version>_setup.exe`**. (Don't take "Source code"; that is the code, not the program.)
3. Run the downloaded file. No administrator rights are needed.
   If Windows shows "Windows protected your PC", click **More info → Run anyway**.

> ### ⬇️ 다운로드
>
> **[최신 버전 받으러 가기](../../releases/latest)**
>
> 1. 위 링크를 누르거나, 이 페이지 **오른쪽의 Releases**에서 가장 위(**Latest** 표시)를 엽니다.
> 2. 아래쪽 **Assets**에서 **`LuXcale-WB-<버전>_setup.exe`**를 누르면 받아집니다. ("Source code"는 코드 파일이라 받을 필요 없어요.)
> 3. 받은 파일을 실행하면 설치됩니다. 관리자 권한은 필요 없어요.
>    "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.
>
> 이미 예전 버전을 쓰고 계시면 새 설치 파일을 그대로 덮어 설치하면 됩니다. 설정과 저장한 결과는 남아요.

> **한국어 요약:** 웨스턴 블롯 원본 TIFF로 밴드를 정량해서 정규화 결과, 그래프, 논문용 그림까지 만드는 Windows 프로그램입니다.
> 화면 밝기는 화면에만 적용되고, 숫자는 항상 원본 이미지에서 계산합니다. 자동으로 정해진 값은 꼭 직접 확인하고 쓰세요.
> 버전별 변경 내용은 [CHANGELOG.md](CHANGELOG.md)에 있습니다.
> Test video : https://youtu.be/RjKfseLv0yM


## What it does

- Opens the raw TIFF, not a screenshot or JPEG; refuses the colorimetric membrane photo
- Levels a tilted blot before measuring; saturated pixels stay flagged after the turn
- Lane boxes: click a band to auto-detect, then drag; each band area of a blot can have its own boxes
- Band intensity = the lane's row profile minus the background, the lowest line that stays under the
  profile (its lower convex hull), so a value can never be negative; touching bands (e.g. p44/p42)
  can be split into separate rows
- Target ÷ loading control, relative to a reference group (= 1)
- Repeated experiments: each normalised on its own; paired t-test (2 groups) or repeated-measures
  ANOVA with Holm-adjusted pairwise tests (3 or more)
- Saves results (CSV, XLSX), the settings that re-run them to the same numbers, the graph,
  and figure strips (PNG, TIFF, SVG, PDF) with a JSON record of angle, crop and contrast

## Install

Run the setup file from [Releases](../../releases/latest) (`LuXcale-WB-<version>_setup.exe`). It installs for your Windows user without administrator rights.

## Versions and updating

What changed in each version, and what is in the code but not yet in an installer, is in
[CHANGELOG.md](CHANGELOG.md). This README describes the code as it is now, so a feature listed
here may be newer than the installer you have.

To update, run the new `setup.exe` over the installed version; there is no need to uninstall first.
Your settings (`%LOCALAPPDATA%\LuXcale`) and saved results stay. A result saved by an older version
records its `app_version` in `settings.json`, and re-running its settings gives the same numbers.

## Running from source

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv installs it).

```bash
uv sync
uv run python -m imquant.ui.wb_app
```

The installer is built with `packaging/build_release.py` (PyInstaller and Inno Setup).

## Tests and validation

```bash
uv run pytest
```

Tests that need the lab's own blots are not part of this repository.
`validation/` holds independent reference implementations and synthetic data with known answers
used to check the measurements and statistics.

## Feedback

- **Bugs and odd results:** open an [issue](../../issues/new/choose) with the *Bug report* form
  (version, imager, the steps, what you expected and what happened).
- **Ideas:** use the *Feature request* form.
- **Blot files:** do not attach unpublished data to a public issue; say in the form that you can
  share one, and we will arrange a private copy.

**피드백:** 버그·이상한 결과는 [Issues](../../issues/new/choose)의 *버그 신고* 양식으로, 원하는 기능은 *기능 제안* 양식으로 남겨 주세요.
미발표 블롯 파일은 공개 이슈에 올리지 말고, 공유 가능하다고 체크해 주시면 따로 받을게요.

## No warranty

Check every automatic choice (lanes, band areas, the blots "Add experiment" picks) before you use the numbers.

## License

MIT — see [LICENSE](LICENSE). Bundled third-party software keeps its own licence;
Qt for Python (PySide6) is used under the GNU LGPL v3.
