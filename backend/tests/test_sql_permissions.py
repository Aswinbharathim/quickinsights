"""Tests for the deterministic, post-generation SQL row-filter enforcement
(app/sql_permissions.py) -- the layer that keeps the LLM out of the access
decision entirely. Every case here was first verified by hand against the
live database during development; these formalize that as a real, checked
suite."""
import pytest

from app.guardrail import is_safe_select
from app.sql_permissions import apply_row_filters, referenced_tables


def test_no_existing_where_clause_gets_one_injected():
    sql = "SELECT name, department FROM `tabDoctor` LIMIT 500"
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology", "ENT"]}})
    assert "WHERE" in out
    assert "`tabDoctor`.`department` IN ('Cardiology', 'ENT')" in out
    assert is_safe_select(out)[0]


def test_existing_where_clause_is_and_ed_not_replaced():
    sql = "SELECT name FROM `tabDoctor` WHERE status = 'Active' ORDER BY name LIMIT 10"
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology"]}})
    assert "status = 'Active'" in out  # original condition preserved
    assert "`tabDoctor`.`department` IN ('Cardiology')" in out
    assert "ORDER BY name" in out
    assert is_safe_select(out)[0]


def test_table_not_referenced_is_left_untouched():
    sql = "SELECT name FROM `tabPatient` LIMIT 10"
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology"]}})
    assert out == sql


def test_join_with_alias_targets_the_right_side():
    sql = (
        "SELECT d.name, a.appointment_date FROM `tabDoctor` d "
        "JOIN `tabAppointment` a ON a.doctor = d.name LIMIT 20"
    )
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology"]}})
    assert "d.`department` IN ('Cardiology')" in out
    assert is_safe_select(out)[0]


def test_empty_allow_list_means_no_rows():
    sql = "SELECT name FROM `tabDoctor` LIMIT 500"
    out = apply_row_filters(sql, {"tabDoctor": {"department": []}})
    assert "1=0" in out
    assert is_safe_select(out)[0]


def test_group_by_boundary_is_respected():
    sql = "SELECT COUNT(*) FROM `tabDoctor` GROUP BY department"
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology"]}})
    assert out.index("WHERE") < out.index("GROUP BY")
    assert is_safe_select(out)[0]


def test_cte_fails_closed_instead_of_executing_unfiltered():
    sql = "WITH x AS (SELECT * FROM `tabDoctor`) SELECT * FROM x"
    with pytest.raises(PermissionError):
        apply_row_filters(sql, {"tabDoctor": {"department": ["Cardiology"]}})


def test_quote_in_value_is_escaped_not_injected():
    sql = "SELECT name FROM `tabDoctor` LIMIT 500"
    out = apply_row_filters(sql, {"tabDoctor": {"department": ["Cardio' OR '1'='1"]}})
    # the malicious value must appear only as an escaped, inert string literal
    assert "''1''=''1" in out
    assert is_safe_select(out)[0]
    # and never as a live, unescaped OR condition that would defeat the filter
    assert " OR '1'='1" not in out


def test_no_filters_returns_sql_unchanged():
    sql = "SELECT name FROM `tabDoctor` LIMIT 10"
    assert apply_row_filters(sql, {}) == sql


def test_referenced_tables_ignores_trailing_keywords_as_aliases():
    # Regression test: FROM `tabDoctor` LIMIT 500 must not be parsed as
    # aliasing the table to "LIMIT".
    assert referenced_tables("SELECT * FROM `tabDoctor` LIMIT 500") == {"tabDoctor"}
    assert referenced_tables("SELECT * FROM `tabDoctor` WHERE 1=1") == {"tabDoctor"}
