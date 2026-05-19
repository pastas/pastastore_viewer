from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QComboBox,
    QSizePolicy,
)


def _qframe_enum(name, scoped_group):
    """Resolve QFrame enum values for both PyQt5 and PyQt6."""
    if hasattr(QFrame, name):
        return getattr(QFrame, name)

    scoped = getattr(QFrame, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"QFrame enum not found: {scoped_group}.{name}")


def _qt_enum(name, scoped_group):
    """Resolve Qt enum values for both PyQt5 and PyQt6."""
    if hasattr(Qt, name):
        return getattr(Qt, name)

    scoped = getattr(Qt, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"Qt enum not found: {scoped_group}.{name}")


def _qabstractitemview_enum(name, scoped_group):
    """Resolve QAbstractItemView enum values for both PyQt5 and PyQt6."""
    if hasattr(QAbstractItemView, name):
        return getattr(QAbstractItemView, name)

    scoped = getattr(QAbstractItemView, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"QAbstractItemView enum not found: {scoped_group}.{name}")


def _qheaderview_enum(name, scoped_group):
    """Resolve QHeaderView enum values for both PyQt5 and PyQt6."""
    if hasattr(QHeaderView, name):
        return getattr(QHeaderView, name)

    scoped = getattr(QHeaderView, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"QHeaderView enum not found: {scoped_group}.{name}")


def _qcombobox_enum(name, scoped_group):
    """Resolve QComboBox enum values for both PyQt5 and PyQt6."""
    if hasattr(QComboBox, name):
        return getattr(QComboBox, name)

    scoped = getattr(QComboBox, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"QComboBox enum not found: {scoped_group}.{name}")


def _qsizepolicy_enum(name, scoped_group):
    """Resolve QSizePolicy enum values for both PyQt5 and PyQt6."""
    if hasattr(QSizePolicy, name):
        return getattr(QSizePolicy, name)

    scoped = getattr(QSizePolicy, scoped_group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)

    raise AttributeError(f"QSizePolicy enum not found: {scoped_group}.{name}")


DOCK_AREA_RIGHT = _qt_enum("RightDockWidgetArea", "DockWidgetArea")
DOCK_AREA_LEFT = _qt_enum("LeftDockWidgetArea", "DockWidgetArea")
DOCK_AREA_BOTTOM = _qt_enum("BottomDockWidgetArea", "DockWidgetArea")
DOCK_AREA_TOP = _qt_enum("TopDockWidgetArea", "DockWidgetArea")

TOOLBUTTON_TEXT_BESIDE_ICON = _qt_enum(
    "ToolButtonTextBesideIcon", "ToolButtonStyle"
)
CONTEXT_MENU_CUSTOM = _qt_enum("CustomContextMenu", "ContextMenuPolicy")
ALIGN_LEFT = _qt_enum("AlignLeft", "AlignmentFlag")

PEN_DASH_LINE = _qt_enum("DashLine", "PenStyle")
MOUSE_BUTTON_LEFT = _qt_enum("LeftButton", "MouseButton")
MOUSE_BUTTON_RIGHT = _qt_enum("RightButton", "MouseButton")

WINDOW_MAXIMIZE_BUTTON_HINT = _qt_enum(
    "WindowMaximizeButtonHint", "WindowType"
)
WINDOW_MODAL = _qt_enum("WindowModal", "WindowModality")
APPLICATION_MODAL = _qt_enum("ApplicationModal", "WindowModality")

ORIENTATION_HORIZONTAL = _qt_enum("Horizontal", "Orientation")

ITEM_IS_SELECTABLE = _qt_enum("ItemIsSelectable", "ItemFlag")
ITEM_IS_EDITABLE = _qt_enum("ItemIsEditable", "ItemFlag")
ITEM_IS_USER_CHECKABLE = _qt_enum("ItemIsUserCheckable", "ItemFlag")
ITEM_IS_ENABLED = _qt_enum("ItemIsEnabled", "ItemFlag")

DISPLAY_ROLE = _qt_enum("DisplayRole", "ItemDataRole")
USER_ROLE = _qt_enum("UserRole", "ItemDataRole")
CHECKED = _qt_enum("Checked", "CheckState")

KEY_DELETE = _qt_enum("Key_Delete", "Key")
WA_TRANSLUCENT_BACKGROUND = _qt_enum(
    "WA_TranslucentBackground", "WidgetAttribute"
)

COLOR_BLUE = _qt_enum("blue", "GlobalColor")
COLOR_RED = _qt_enum("red", "GlobalColor")
COLOR_BLACK = _qt_enum("black", "GlobalColor")

SELECTION_BEHAVIOR_SELECT_ROWS = _qabstractitemview_enum(
    "SelectRows", "SelectionBehavior"
)
SELECTION_MODE_EXTENDED = _qabstractitemview_enum(
    "ExtendedSelection", "SelectionMode"
)
EDIT_TRIGGERS_NONE = _qabstractitemview_enum("NoEditTriggers", "EditTrigger")
SCROLL_HINT_POSITION_AT_CENTER = _qabstractitemview_enum(
    "PositionAtCenter", "ScrollHint"
)

HEADER_RESIZE_INTERACTIVE = _qheaderview_enum("Interactive", "ResizeMode")
HEADER_RESIZE_STRETCH = _qheaderview_enum("Stretch", "ResizeMode")

COMBO_SIZE_ADJUST_MIN_CONTENTS_WITH_ICON = _qcombobox_enum(
    "AdjustToMinimumContentsLengthWithIcon", "SizeAdjustPolicy"
)

SIZE_POLICY_FIXED = _qsizepolicy_enum("Fixed", "Policy")

FRAME_SHAPE_NO_FRAME = _qframe_enum("NoFrame", "Shape")