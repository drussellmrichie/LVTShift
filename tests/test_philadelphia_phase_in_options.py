"""The abatement phase-in's options and the output names that keep their runs apart."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from philadelphia_abatement_phase_in import DEFAULT_SETTINGS, output_tag  # noqa: E402


def test_default_run_keeps_its_file_names():
    assert output_tag(dict(DEFAULT_SETTINGS)) == ""


def test_any_other_option_gets_its_own_name():
    """The one-pager reads the value-share run; the default run's outputs must never be overwritten by it."""
    assert output_tag(dict(homestead_order="value_share", baseline="rate", revalue_bare_lots=True)) == "_value_share_rate_bare"
    assert output_tag(dict(homestead_order="building_first", baseline="rate", revalue_bare_lots=True)) == "_building_first_rate_bare"
    assert output_tag(dict(homestead_order="building_first", baseline="levy", revalue_bare_lots=True)) == "_building_first_levy_bare"
    assert output_tag(dict(homestead_order="land_first", baseline="levy", revalue_bare_lots=False)) == "_land_first_levy"
