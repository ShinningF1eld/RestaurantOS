from sqlalchemy import text

from conftest import engine


def row_count(table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_fixture_data_is_present_only_during_its_test(auth_user):
    assert auth_user["id"]
    assert row_count("users") == 1
    assert row_count("organizations") == 1
    assert row_count("memberships") == 1


def test_previous_test_rows_are_cleared_before_the_next_case():
    assert row_count("users") == 0
    assert row_count("organizations") == 0
    assert row_count("memberships") == 0
