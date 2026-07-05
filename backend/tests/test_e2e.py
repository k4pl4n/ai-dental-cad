"""End-to-end pipeline test on the synthetic scan, in mock-Claude mode.

Run:  AIDCAD_MOCK=1 python tests/test_e2e.py
Exercises: L1 ingest → L2 render+perceive → L3 plan → approve →
L4 framework → L5 generate → L6 validate → report → package.
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AIDCAD_MOCK", "1")

from app.models.schemas import Case, CaseStatus  # noqa: E402
from app.services import pipeline, store  # noqa: E402
from tests.make_synthetic_scan import make_arch  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def main():
    os.makedirs(store.DATA_DIR, exist_ok=True)
    scan_path = os.path.join(store.DATA_DIR, "test_synthetic_upper.stl")
    make_arch(scan_path)

    case = Case(description="Full arch rehabilitation, patient has generalised wear")
    store.save_case(case)

    print("\n== analyse ==")
    case = pipeline.analyse(case, scan_path, None)
    check("analyse completes", case.status in
          (CaseStatus.PLAN_REVIEW, CaseStatus.ASSESSMENT_REVIEW), case.status.value)
    check("scan ingested", len(case.scans) == 1)
    if case.scans:
        s = case.scans[0]
        check("detected upper arch", s.arch.value == "upper", s.arch.value)
        check("orientation normalised (width > depth)",
              s.measurements.mesiodistal_width_mm > s.measurements.anteroposterior_depth_mm * 0.9,
              f"w={s.measurements.mesiodistal_width_mm:.1f} d={s.measurements.anteroposterior_depth_mm:.1f}")
    check("perception present", case.perception is not None)
    if case.perception:
        check("16 tooth positions assessed", len(case.perception.teeth) == 16)
    check("plan produced", case.plan is not None)
    if case.plan:
        check("plan has restorations", len(case.plan.restorations) > 0,
              f"{len(case.plan.restorations)} planned")
        check("no sanity violations", not case.plan.sanity_violations,
              str(case.plan.sanity_violations))

    print("\n== renders ==")
    rdir = os.path.join(store.DATA_DIR, "cases", case.case_id, "renders")
    pngs = [f for f in os.listdir(rdir)] if os.path.isdir(rdir) else []
    check("five views rendered", len([p for p in pngs if p.endswith(".png")]) == 5, str(pngs))

    if case.plan is None:
        print(f"\nSTOPPING — no plan (case error: {case.error})")
        print(f"{len(FAILURES) or 'no'} failures so far: {FAILURES}")
        sys.exit(1)

    print("\n== design ==")
    case.plan.approved = True
    case = pipeline.design(case)
    check("design completes", case.status == CaseStatus.COMPLETE, case.status.value or str(case.error))
    gen_ok = [r for r in case.restorations if not r.failed]
    check("restorations generated", len(gen_ok) == len(case.plan.restorations),
          f"{len(gen_ok)}/{len(case.plan.restorations)}")

    print("\n== validation ==")
    check("validation ran", case.validation is not None)
    if case.validation:
        for c in case.validation.checks:
            check(f"check {c.check_number} ({c.name})", c.passed, c.details)

    print("\n== package ==")
    check("package built", bool(case.package_path and os.path.exists(case.package_path)))
    if case.package_path and os.path.exists(case.package_path):
        with zipfile.ZipFile(case.package_path) as z:
            names = z.namelist()
        check("fabrication STLs in zip",
              any("_FABRICATION_READY.stl" in n for n in names))
        check("case report PDF in zip", "case_report.pdf" in names)
        check("README in zip", "README.txt" in names)
        check("assembly in zip", "assembly_all_restorations.stl" in names)
    check("traffic light computed", pipeline.traffic_light(case) in ("green", "yellow", "red"),
          pipeline.traffic_light(case))

    print(f"\n{'ALL CHECKS PASSED' if not FAILURES else f'{len(FAILURES)} FAILURES: {FAILURES}'}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
