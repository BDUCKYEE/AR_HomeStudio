"""메시 개선 실험 비교표: experiments/ 아래 결과를 모아 마크다운 표로 (status-cv.md 용).

사용 (메인 .venv): python -m cv.recon.compare_experiments [대상]
출력: 화면 + ${SHARED_DIR}/meshes/experiments/compare_<이름>.md

열 설명
- 시간: 그 방법만의 처리 시간 (원본 TSDF 는 build_room 전체). 2DGS 는 내보내기 + BA 시도 + 학습 + 메시 + 정리
- 벽 평면도: 메시 = 기준 평면(proxy-ransac 벽) ±6cm 안 표면의 RMS / 20cm 타일 잔차(국소 거칠기).
  프록시 = 입력 점이 그 프록시의 벽 평면 ±10cm 안에서 떨어진 RMS (평면 자체는 완전히 평평함)
- 구멍: 메시 = 벽 5cm 칸 중 표면이 있는 비율(덮임) / 열린 경계 길이. 프록시 = 평면이라 구멍 없음, 괄호는 입력 점 덮임
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from cv.common.config import shared_dir
from cv.recon import experiments as ex

MEASURED = (2.5, 3.3)   # 실측 방 크기 (m), status-cv.md / PROJECT_BRIEF


def proxy_row(name: str, p: dict, P: np.ndarray, time_s, preview: str) -> dict:
    walls = [pl for pl in p["planes"] if pl["type"] == "wall"]
    st = [ex.plane_stats(P, pl, band=0.10) for pl in walls]
    rms = [s["rms_m"] for s in st if s["rms_m"] is not None]
    cov = np.mean([s["coverage"] for s in st]) if st else float("nan")
    size = sorted(p["room"]["size_m"]) if p["room"]["size_m"] else [0, 0]
    labels = sorted({b["label"] for b in p["boxes"]})
    return {"방법": name, "시간": time_s, "삼각형/상자": f"벽 {len(walls)}, 상자 {len(p['boxes'])}"
            + (f", 문/창 {len(p['openings'])}" if p.get("openings") else ""),
            "방 크기": f"{size[0]:.2f}×{size[1]:.2f}m, 높이 {p['room']['height_m'] or 0:.2f}m",
            "벽 평면도": f"평면 (점 {np.mean(rms) * 1000:.0f}mm)" if rms else "평면",
            "구멍": f"없음 (점 덮임 {cov:.0%})", "미리보기": preview,
            "_labels": ", ".join(labels) if labels and labels != ["furniture"] else ""}


def mesh_row(name, m: dict, time_s, preview) -> dict:
    return {"방법": name, "시간": time_s, "삼각형/상자": f"{m['triangles']:,}",
            "방 크기": "-",
            "벽 평면도": f"{m.get('wall_rms_mm')}mm / {m.get('wall_local_rms_mm')}mm",
            "구멍": f"덮임 {m.get('wall_coverage', 0):.0%} / 경계 {m['boundary_m']:.0f}m", "미리보기": preview}


def fmt_t(t) -> str:
    if t is None:
        return "-"
    return f"{t:.0f}s" if t < 120 else f"{t / 60:.1f}분"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    a = ap.parse_args()
    src = ex.resolve_source(a.target)
    root = shared_dir() / "meshes" / "experiments"
    rel = lambda p: str(Path(p).relative_to(shared_dir()))   # noqa: E731
    P, _ = ex.load_points(src)
    rows = []

    sm = root / "smooth" / src.stem / "metrics.json"
    if sm.is_file():
        d = json.loads(sm.read_text())["variants"]
        for k, m in d.items():
            nm = "원본 TSDF (기준)" if k == "orig" else f"smooth {k}"
            t = None if k == "orig" else m["time_s"]
            rows.append(mesh_row(nm, m, t, rel(root / "smooth" / src.stem / m["preview"])))
    for f in sorted((root / "2dgs" / src.stem).glob("2dgs_*.json")):
        r = json.loads(f.read_text())
        t = sum(v for v in r["times_s"].values())
        ba = r.get("ba", {})
        t += ba.get("time_total_s", 0) if "ba" not in r["times_s"] else 0
        rows.append(mesh_row(f"2DGS {r['tag']} (가우시안 {r['gaussians']:,})", r["metrics"], t,
                             rel(root / "2dgs" / src.stem / r["preview"])))
    pr = root / "proxy-ransac" / src.stem / "proxy.json"
    if pr.is_file():
        p = json.loads(pr.read_text())
        rows.append(proxy_row("평면+상자 (RANSAC)", p, P, p["stats"]["time_s"], rel(pr.with_name("preview.png"))))
    for f in sorted((root / "spatiallm" / src.stem).glob("proxy*.json")):
        p = json.loads(f.read_text())
        s = p["stats"]
        nm = f"SpatialLM {s['input']} s{s['seed']}"
        rows.append(proxy_row(nm, p, P, s["time_infer_s"], rel(f.with_suffix(".png"))))

    cols = ["방법", "시간", "삼각형/상자", "방 크기", "벽 평면도", "구멍", "미리보기"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        r = dict(r, 시간=fmt_t(r["시간"]), 미리보기=f"`{r['미리보기']}`")
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    lab = [f"- {r['방법']}: {r['_labels']}" for r in rows if r.get("_labels")]
    md = (f"대상 `{src.stem}` (실측 {MEASURED[0]}×{MEASURED[1]}m). 미리보기 경로는 `${{SHARED_DIR}}` 기준.\n\n"
          + "\n".join(lines) + ("\n\n상자 종류 (SpatialLM)\n" + "\n".join(lab) if lab else "") + "\n")
    print(md)
    out = root / f"compare_{src.stem}.md"
    out.write_text(md, encoding="utf-8")
    ex.log(f"저장 {out}")


if __name__ == "__main__":
    main()
