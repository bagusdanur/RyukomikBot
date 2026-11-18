from types import SimpleNamespace

from views.role_views import ZODIAC_NAMES, ZodiacRoleView, zodiac_roles


def test_zodiac_view_preserves_legacy_custom_id():
    view = ZodiacRoleView()
    select = view.children[0]
    assert select.custom_id == "zodiac_select"
    assert [option.value for option in select.options] == list(ZODIAC_NAMES)
    assert view.timeout is None


def test_zodiac_roles_only_returns_zodiac_roles():
    member = SimpleNamespace(
        roles=[
            SimpleNamespace(name="@everyone"),
            SimpleNamespace(name="Staff"),
            SimpleNamespace(name="Leo"),
        ]
    )
    assert [role.name for role in zodiac_roles(member)] == ["Leo"]
