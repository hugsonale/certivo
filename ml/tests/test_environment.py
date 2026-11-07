from __future__ import annotations

from certivo_ml import environment


def test_python_3_12_and_3_13_on_64_bit_are_accepted():
    for version in ((3, 12), (3, 13)):
        assert environment.problems_with(version, 64, False) == []


def test_too_old_a_python_is_refused_with_the_reason():
    [problem] = environment.problems_with((3, 11), 64, False)
    assert "3.11" in problem and "3.12" in problem and "newer" in problem


def test_too_new_a_python_is_refused_with_the_reason():
    [problem] = environment.problems_with((3, 15), 64, False)
    assert "3.15" in problem and "compile" in problem


def test_32_bit_and_free_threaded_builds_are_refused():
    assert any("32-bit" in p for p in environment.problems_with((3, 12), 32, False))
    assert any("free-threaded" in p for p in environment.problems_with((3, 13), 64, True))


def test_several_problems_are_all_reported():
    assert len(environment.problems_with((3, 15), 32, True)) == 3


def test_the_summary_names_the_python():
    assert environment.summary().startswith("Python 3.")
