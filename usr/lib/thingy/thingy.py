#!/usr/bin/python3
import gettext
import gi
import hashlib
import json
import locale
import os
import setproctitle
import subprocess
import threading
import uuid
gi.require_version('Gtk', '3.0')
gi.require_version('XApp', '1.0')
gi.require_version('GnomeDesktop', '3.0')
from gi.repository import Gtk, Gio, GLib, XApp, Pango, GdkPixbuf, Gdk, GnomeDesktop

setproctitle.setproctitle("thingy")

# i18n
APP = 'thingy'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

DOCUMENT_CATEGORIES = [
    ("favorites", _("Favorites"), "emblem-xapp-favorite", "starred", (
        "*/*",
    )),
    ("text-files", _("Text Files"), "accessories-text-editor", "text-x-generic", (
        "text/plain", "text/markdown", "text/x-markdown",
    )),
    ("documents", _("PDFs"), "xreader", "application-pdf", (
        "application/pdf", "application/postscript", "application/oxps",
        "application/vnd.ms-xpsdocument", "image/vnd.djvu",
        "image/vnd.djvu+multipage",
    )),
    ("books", _("Books"), "xepub", "application-epub+zip", (
        "application/epub+zip", "application/x-mobipocket-ebook",
        "application/vnd.amazon.mobi8-ebook", "application/x-fictionbook+xml",
        "application/x-sony-bbeb", "application/vnd.comicbook+zip",
        "application/vnd.comicbook-rar", "application/x-cb7",
        "application/x-cbt", "application/x-cbr", "application/x-cbz",
    )),
    ("writer-documents", _("Documents"), "libreoffice-writer", "x-office-document", (
        "application/rtf", "text/rtf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
        "application/vnd.ms-word.document.macroEnabled.12",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.text-template",
        "application/vnd.oasis.opendocument.text-flat-xml",
    )),
    ("spreadsheets", _("Spreadsheets"), "libreoffice-calc", "x-office-spreadsheet", (
        "text/csv", "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.spreadsheet",
    )),
    ("presentations", _("Presentations"), "libreoffice-impress", "x-office-presentation", (
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
    )),
    ("drawings", _("Drawings"), "libreoffice-draw", "x-office-drawing", (
        "application/vnd.oasis.opendocument.graphics",
        "application/vnd.oasis.opendocument.graphics-template",
        "application/vnd.oasis.opendocument.graphics-flat-xml",
        "application/vnd.sun.xml.draw",
        "application/vnd.sun.xml.draw.template",
        "application/vnd.stardivision.draw",
    )),
    ("databases", _("Databases"), "libreoffice-base", "application-vnd.oasis.opendocument.database", (
        "application/vnd.oasis.opendocument.database",
        "application/vnd.sun.xml.base",
    )),
    ("pictures", _("Pictures"), "xviewer", "image-x-generic", (
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff",
        "image/bmp", "image/svg+xml", "image/heif", "image/avif",
        "image/x-xcf", "image/x-canon-cr2", "image/x-nikon-nef",
    )),
    ("audio", _("Audio"), "rhythmbox", "audio-x-generic", (
        "audio/*",
    )),
    ("videos", _("Videos"), "io.github.celluloid_player.Celluloid", "video-x-generic", (
        "video/*",
    )),
]

DEFAULT_GROUP_ICON = "text-x-generic"
DEFAULT_HIDDEN_GROUPS = ["drawings", "presentations", "databases"]

# Used as a decorator to run things in the background
def _async(func):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        return thread
    return wrapper

# Used as a decorator to run things in the main loop, from another thread
def idle(func):
    def wrapper(*args):
        GLib.idle_add(func, *args)
    return wrapper

class Application(Gtk.Application):
    # Main initialization routine
    def __init__(self, application_id, flags):
        Gtk.Application.__init__(self, application_id=application_id, flags=flags)
        self.connect("activate", self.activate)

        GLib.set_prgname("thingy")

    def activate(self, application):
        windows = self.get_windows()
        if (len(windows) > 0):
            window = windows[0]
            window.present()
            window.show_all()
        else:
            window = Window(self)
            self.add_window(window.window)
            window.window.show_all()

class Window():

    def __init__(self, application):

        self.application = application
        self.settings = Gio.Settings(schema_id="org.x.thingy")
        self.groups_path = os.path.join(GLib.get_user_config_dir(), APP, "groups.json")
        self.groups_config = self.load_groups_config()

        # Dark mode manager
        # keep a reference to it (otherwise it gets randomly garbage collected)
        self.dark_mode_manager = XApp.DarkModeManager.new(prefer_dark_mode=False)

        self.recent_manager = Gtk.RecentManager()
        self.favorites_manager = XApp.Favorites.get_default()
        self.thumbnail_factory = GnomeDesktop.DesktopThumbnailFactory.new(
            GnomeDesktop.DesktopThumbnailSize.LARGE)

        # Set the Glade file
        gladefile = "/usr/share/thingy/thingy.ui"
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file(gladefile)
        self.window = self.builder.get_object("main_window")
        self.window.set_title(_("Library"))
        XApp.set_window_icon_name (self.window, "thingy")

        provider = Gtk.CssProvider()
        provider.load_from_path("/usr/share/thingy/thingy.css")
        screen = Gdk.Display.get_default_screen(Gdk.Display.get_default())
        # I was unable to found instrospected version of this
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Menubar
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)
        menu = self.builder.get_object("main_menu")
        item = Gtk.MenuItem()
        item.set_label(_("Groups"))
        item.connect("activate", self.open_groups)
        menu.append(item)
        item = Gtk.MenuItem()
        item.set_label(_("Clear Recent Documents"))
        item.connect("activate", self.clear_recent_documents)
        menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem()
        item.set_label(_("About"))
        item.connect("activate", self.open_about)
        key, mod = Gtk.accelerator_parse("F1")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        menu.append(item)
        item = Gtk.MenuItem(label=_("Quit"))
        item.connect('activate', self.on_menu_quit)
        key, mod = Gtk.accelerator_parse("<Control>Q")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        key, mod = Gtk.accelerator_parse("<Control>W")
        item.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)
        menu.append(item)
        menu.show_all()

        self.app_stack = self.builder.get_object("app_stack")

        # Preserve window state
        self.width = self.settings.get_int("width")
        self.height = self.settings.get_int("height")
        self.maximized = self.settings.get_boolean("maximized")
        if self.maximized:
            self.window.maximize()
        else:
            self.window.resize(self.width, self.height)

        self.window.connect("configure-event", self.on_window_resized)
        self.window.connect("window-state-event", self.on_window_state_changed)
        self.window.connect("destroy", self.on_window_destroyed)

        # Load data
        self.rebuild_categories()

        self.app_stack.connect("notify::visible-child-name", self.on_app_changed)
        if self.categories:
            self.load_documents()
        self.recent_manager.connect("changed", self.load_documents)
        self.favorites_manager.connect("changed", self.load_documents)

    def load_groups_config(self):
        default = self.default_groups_config()
        try:
            with open(self.groups_path, encoding="utf-8") as config_file:
                config = json.load(config_file)
            hidden = config.get("hidden_groups", [])
            custom = config.get("custom_groups", [])
            order = config.get("group_order", [])
            if not all(isinstance(value, list) for value in (hidden, custom, order)):
                raise ValueError("Invalid document groups configuration")
            default["hidden_groups"] = [item for item in hidden if isinstance(item, str)]
            default["custom_groups"] = [item for item in custom if self.valid_custom_group(item)]
            default["group_order"] = [item for item in order if isinstance(item, str)]
            active_group = config.get("active_group")
            if isinstance(active_group, str):
                default["active_group"] = active_group
        except (OSError, ValueError, json.JSONDecodeError) as e:
            if not isinstance(e, FileNotFoundError):
                print("Could not load document groups: %s" % e)
        valid_ids = [category[0] for category in DOCUMENT_CATEGORIES]
        valid_ids.extend("custom-" + group["id"] for group in default["custom_groups"])
        default["hidden_groups"] = [item for item in default["hidden_groups"]
                                    if item in valid_ids]
        default["group_order"] = [item for item in default["group_order"] if item in valid_ids]
        if "favorites" not in default["group_order"]:
            default["group_order"].insert(0, "favorites")
        default["group_order"].extend(item for item in valid_ids
                                      if item not in default["group_order"])
        if default["active_group"] not in valid_ids:
            default["active_group"] = "favorites"
        return default

    @staticmethod
    def default_groups_config():
        return {
            "hidden_groups": list(DEFAULT_HIDDEN_GROUPS),
            "custom_groups": [],
            "group_order": [category[0] for category in DOCUMENT_CATEGORIES],
            "active_group": "favorites",
        }

    @staticmethod
    def valid_custom_group(group):
        return (isinstance(group, dict) and
                all(isinstance(group.get(key), str) and group.get(key)
                    for key in ("id", "name", "icon")) and
                isinstance(group.get("mime_types"), list) and
                all(isinstance(mime_type, str) and mime_type
                    for mime_type in group["mime_types"]) and
                (group.get("path") is None or isinstance(group.get("path"), str)))

    def save_groups_config(self):
        directory = os.path.dirname(self.groups_path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        temporary_path = self.groups_path + ".tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as config_file:
                json.dump(self.groups_config, config_file, indent=2, ensure_ascii=False)
                config_file.write("\n")
            os.replace(temporary_path, self.groups_path)
        except OSError as e:
            print("Could not save document groups: %s" % e)

    def rebuild_categories(self):
        selected = (self.app_stack.get_visible_child_name() or
                    self.groups_config.get("active_group"))
        for child in self.app_stack.get_children():
            self.app_stack.remove(child)

        self.categories = {}
        hidden = self.groups_config["hidden_groups"]
        available = {
            category_id: (title, self.get_standard_icon(icon, fallback_icon),
                          mime_types, None)
            for category_id, title, icon, fallback_icon, mime_types in DOCUMENT_CATEGORIES
        }
        for group in self.groups_config["custom_groups"]:
            icon = self.get_sidebar_icon(group["icon"])
            available["custom-" + group["id"]] = (group["name"], icon,
                                                     tuple(group["mime_types"]),
                                                     group.get("path"))
        for category_id in self.groups_config["group_order"]:
            if category_id in available and category_id not in hidden:
                self.add_category(category_id, *available[category_id])

        if selected in self.categories:
            self.app_stack.set_visible_child_name(selected)
        elif self.categories:
            self.app_stack.set_visible_child_name(next(iter(self.categories)))
        self.set_sidebar_icon_size(self.builder.get_object("app_sidebar"))

    def add_category(self, category_id, title, icon, mime_types, path):
        page, flowbox, content_stack = self.create_category_page()
        self.categories[category_id] = (mime_types, path, flowbox, content_stack)
        self.app_stack.add_titled(page, category_id, title)
        self.app_stack.child_set_property(page, "icon-name", icon)

    @staticmethod
    def get_standard_icon(icon, fallback_icon):
        icon_theme = Gtk.IconTheme.get_default()
        if icon_theme is not None and icon_theme.has_icon(icon):
            return icon
        return fallback_icon

    @staticmethod
    def get_sidebar_icon(icon):
        if not os.path.isfile(icon):
            return icon
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon, 32, 32, True)
            digest = hashlib.sha256(os.path.abspath(icon).encode("utf-8")).hexdigest()[:16]
            icon_name = "thingy-custom-%s" % digest
            Gtk.IconTheme.add_builtin_icon(icon_name, 32, pixbuf)
            return icon_name
        except GLib.Error as e:
            print("Could not load custom group icon: %s" % e)
            return DEFAULT_GROUP_ICON

    @staticmethod
    def create_group_icon(icon):
        if os.path.isfile(icon):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon, 32, 32, True)
                return Gtk.Image.new_from_pixbuf(pixbuf)
            except GLib.Error as e:
                print("Could not load custom group icon: %s" % e)
        return Gtk.Image.new_from_icon_name(icon or DEFAULT_GROUP_ICON, Gtk.IconSize.DND)

    def set_sidebar_icon_size(self, widget):
        if isinstance(widget, Gtk.Image):
            storage_type = widget.get_storage_type()
            if storage_type == Gtk.ImageType.ICON_NAME:
                icon_name, unused_size = widget.get_icon_name()
                widget.set_from_icon_name(icon_name, Gtk.IconSize.DND)
            elif storage_type == Gtk.ImageType.GICON:
                gicon, unused_size = widget.get_gicon()
                widget.set_from_gicon(gicon, Gtk.IconSize.DND)
        elif isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                self.set_sidebar_icon_size(child)

    def create_category_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_stack = Gtk.Stack()
        content_stack.set_hexpand(True)
        content_stack.set_vexpand(True)

        scrolled = Gtk.ScrolledWindow()
        viewport = Gtk.Viewport()
        viewport.set_shadow_type(Gtk.ShadowType.NONE)
        viewport.get_style_context().add_class("view")
        flowbox = Gtk.FlowBox()
        flowbox.set_valign(Gtk.Align.START)
        flowbox.set_margin_start(8)
        flowbox.set_margin_end(8)
        flowbox.set_margin_top(8)
        flowbox.set_margin_bottom(8)
        flowbox.set_homogeneous(True)
        flowbox.set_min_children_per_line(1)
        flowbox.set_max_children_per_line(10)
        viewport.add(flowbox)
        scrolled.add(viewport)
        content_stack.add_named(scrolled, "page_documents")

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_icon_name("xsi-emblem-documents-symbolic", Gtk.IconSize.DIALOG)
        image.set_pixel_size(96)
        image.set_margin_bottom(20)
        image.get_style_context().add_class("dim-label")
        empty.pack_start(image, False, False, 0)
        title = Gtk.Label(label=_("No documents found"))
        title.set_markup("<span weight=\"bold\" size=\"large\">%s</span>" %
                         GLib.markup_escape_text(_("No documents found")))
        title.get_style_context().add_class("dim-label")
        empty.pack_start(title, False, False, 0)
        description = Gtk.Label(label=_("You can add documents by opening them or by marking them as favorites"))
        description.set_line_wrap(True)
        description.get_style_context().add_class("dim-label")
        empty.pack_start(description, False, False, 0)
        content_stack.add_named(empty, "page_empty")
        content_stack.get_style_context().add_class("view")
        page.pack_start(content_stack, True, True, 0)
        page.show_all()
        return page, flowbox, content_stack

    def on_window_resized(self, window, event):
        if not self.maximized:
            self.width, self.height = window.get_size()
        return False

    def on_window_state_changed(self, window, event):
        self.maximized = window.get_window().get_state() & Gdk.WindowState.MAXIMIZED == Gdk.WindowState.MAXIMIZED

    def on_window_destroyed(self, window):
        self.settings.set_int("width", self.width)
        self.settings.set_int("height", self.height)
        self.settings.set_boolean("maximized", self.maximized)

    def clear_recent_documents(self, widget):
        dialog = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=_("Clear all recent documents?"))
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.format_secondary_text(
            _("This will clear the history of recent documents for all applications."))
        clear_button = dialog.add_button(_("Clear"), Gtk.ResponseType.OK)
        clear_button.get_style_context().add_class("destructive-action")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            try:
                self.recent_manager.purge_items()
            except GLib.Error as e:
                print("Could not clear recent documents: %s" % e)

    def open_groups(self, widget):
        dialog = Gtk.Dialog(title=_("Groups"), transient_for=self.window,
                            modal=True, destroy_with_parent=True)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        dialog.set_default_size(560, 480)
        dialog.set_resizable(True)
        dialog.get_content_area().set_hexpand(True)
        dialog.get_content_area().set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_border_width(12)
        content.set_hexpand(True)
        content.set_vexpand(True)
        group_list = Gtk.ListBox()
        group_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        group_list.set_hexpand(True)
        group_list.set_vexpand(True)
        group_scroll = Gtk.ScrolledWindow()
        group_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        group_scroll.set_shadow_type(Gtk.ShadowType.IN)
        group_scroll.set_hexpand(True)
        group_scroll.set_vexpand(True)
        group_scroll.add(group_list)
        group_frame = Gtk.Frame()
        group_frame.set_shadow_type(Gtk.ShadowType.IN)
        group_frame.set_hexpand(True)
        group_frame.set_vexpand(True)
        group_frame.add(group_scroll)
        content.pack_start(group_frame, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_button = self.create_icon_button("list-add-symbolic", _("Add"))
        edit_button = self.create_icon_button("document-edit-symbolic", _("Edit"))
        delete_button = self.create_icon_button("edit-delete-symbolic", _("Remove"))
        reset_button = Gtk.Button.new_with_label(_("Reset to Defaults"))
        up_button = self.create_icon_button("go-up-symbolic", _("Move Up"))
        down_button = self.create_icon_button("go-down-symbolic", _("Move Down"))
        edit_button.set_sensitive(False)
        delete_button.set_sensitive(False)
        up_button.set_sensitive(False)
        down_button.set_sensitive(False)
        controls.pack_start(add_button, False, False, 0)
        controls.pack_start(edit_button, False, False, 0)
        controls.pack_start(delete_button, False, False, 0)
        controls.pack_end(reset_button, False, False, 0)
        controls.pack_end(down_button, False, False, 0)
        controls.pack_end(up_button, False, False, 0)
        content.pack_start(controls, False, False, 0)
        dialog.get_content_area().pack_start(content, True, True, 0)

        group_list.connect("row-selected", self.on_group_selected,
                           edit_button, delete_button, up_button, down_button)
        group_list.connect("row-activated", self.edit_group_row, dialog, group_list)
        add_button.connect("clicked", self.add_custom_group, dialog, group_list)
        edit_button.connect("clicked", self.edit_custom_group, dialog, group_list)
        delete_button.connect("clicked", self.delete_custom_group, dialog, group_list)
        reset_button.connect("clicked", self.reset_groups, dialog, group_list)
        up_button.connect("clicked", self.move_group, group_list, -1)
        down_button.connect("clicked", self.move_group, group_list, 1)
        self.refresh_group_list(group_list)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    @staticmethod
    def create_icon_button(icon_name, tooltip):
        button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        button.set_tooltip_text(tooltip)
        return button

    def reset_groups(self, button, parent, listbox):
        prompt = Gtk.MessageDialog(
            transient_for=parent, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.CANCEL,
            text=_("Reset to defaults?"))
        prompt.format_secondary_text(
            _("This will reset the group list to defaults and remove custom groups."))
        prompt.add_button(_("Reset"), Gtk.ResponseType.OK)
        response = prompt.run()
        prompt.destroy()
        if response == Gtk.ResponseType.OK:
            self.groups_config = self.default_groups_config()
            self.save_groups_config()
            self.rebuild_categories()
            self.refresh_group_list(listbox)
            if self.categories:
                self.load_documents()

    def on_group_toggled(self, switch, param, category_id):
        hidden = self.groups_config["hidden_groups"]
        if switch.get_active() and category_id in hidden:
            hidden.remove(category_id)
        elif not switch.get_active() and category_id not in hidden:
            hidden.append(category_id)
        self.save_groups_config()
        self.rebuild_categories()
        if self.categories:
            self.load_documents()

    def get_custom_group(self, group_id):
        return next((group for group in self.groups_config["custom_groups"]
                     if group["id"] == group_id), None)

    def add_custom_group(self, button, parent, listbox):
        group = self.run_group_editor(parent)
        if group is not None:
            self.groups_config["custom_groups"].append(group)
            group_id = "custom-" + group["id"]
            self.groups_config["group_order"].append(group_id)
            self.groups_changed(listbox, group_id)

    def edit_custom_group(self, button, parent, listbox):
        row = listbox.get_selected_row()
        if row is not None and row.group_id.startswith("custom-"):
            self.edit_group_row(listbox, row, parent, listbox)

    def edit_group_row(self, listbox, row, parent, group_list):
        if not row.group_id.startswith("custom-"):
            return
        group = self.get_custom_group(row.group_id[len("custom-"):])
        updated = self.run_group_editor(parent, group)
        if updated is not None:
            group.update(updated)
            self.groups_changed(group_list, row.group_id)

    def delete_custom_group(self, button, parent, listbox):
        row = listbox.get_selected_row()
        if row is None:
            return
        if not row.group_id.startswith("custom-"):
            return
        group = self.get_custom_group(row.group_id[len("custom-"):])
        prompt = Gtk.MessageDialog(transient_for=parent, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.CANCEL,
                                   text=_("Remove '%s'?") % group["name"])
        prompt.add_button(_("Remove"), Gtk.ResponseType.OK)
        response = prompt.run()
        prompt.destroy()
        if response == Gtk.ResponseType.OK:
            self.groups_config["custom_groups"].remove(group)
            group_id = "custom-" + group["id"]
            self.groups_config["group_order"].remove(group_id)
            if group_id in self.groups_config["hidden_groups"]:
                self.groups_config["hidden_groups"].remove(group_id)
            self.groups_changed(listbox)

    def group_details(self, group_id):
        for category_id, title, icon, fallback_icon, unused_mime_types in DOCUMENT_CATEGORIES:
            if category_id == group_id:
                return title, self.get_standard_icon(icon, fallback_icon), None
        if group_id.startswith("custom-"):
            group = self.get_custom_group(group_id[len("custom-"):])
            if group:
                return group["name"], group["icon"], group
        return None

    @staticmethod
    def format_content_type(mime_type):
        description = Gio.content_type_get_description(mime_type)
        if description and description != mime_type:
            return "%s (%s)" % (description, mime_type)
        return mime_type

    def refresh_group_list(self, listbox, selected_id=None):
        for child in listbox.get_children():
            listbox.remove(child)
        selected_row = None
        for group_id in self.groups_config["group_order"]:
            details = self.group_details(group_id)
            if details is None:
                continue
            title, icon, custom_group = details
            row = Gtk.ListBoxRow()
            row.group_id = group_id
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_border_width(8)
            box.pack_start(self.create_group_icon(icon), False, False, 0)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            labels.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
            if custom_group:
                detail = ", ".join(self.format_content_type(mime_type)
                                   for mime_type in custom_group["mime_types"])
                if custom_group.get("path"):
                    detail += " — " + custom_group["path"]
                detail_label = Gtk.Label(label=detail, xalign=0)
                detail_label.set_ellipsize(Pango.EllipsizeMode.END)
                detail_label.get_style_context().add_class("dim-label")
                labels.pack_start(detail_label, False, False, 0)
            box.pack_start(labels, True, True, 0)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.set_active(group_id not in self.groups_config["hidden_groups"])
            switch.connect("notify::active", self.on_group_toggled, group_id)
            box.pack_end(switch, False, False, 0)
            row.add(box)
            listbox.add(row)
            if group_id == selected_id:
                selected_row = row
        listbox.show_all()
        if selected_row:
            listbox.select_row(selected_row)

    def on_group_selected(self, listbox, row, edit_button, delete_button,
                          up_button, down_button):
        if row is None:
            edit_button.set_sensitive(False)
            delete_button.set_sensitive(False)
            up_button.set_sensitive(False)
            down_button.set_sensitive(False)
            return
        custom = row.group_id.startswith("custom-")
        edit_button.set_sensitive(custom)
        delete_button.set_sensitive(custom)
        index = self.groups_config["group_order"].index(row.group_id)
        up_button.set_sensitive(index > 0)
        down_button.set_sensitive(index < len(self.groups_config["group_order"]) - 1)

    def move_group(self, button, listbox, direction):
        row = listbox.get_selected_row()
        if row is None:
            return
        order = self.groups_config["group_order"]
        index = order.index(row.group_id)
        destination = index + direction
        if destination < 0 or destination >= len(order):
            return
        order[index], order[destination] = order[destination], order[index]
        self.save_groups_config()
        self.rebuild_categories()
        self.refresh_group_list(listbox, row.group_id)
        if self.categories:
            self.load_documents()

    def groups_changed(self, listbox, selected_id=None):
        self.save_groups_config()
        self.rebuild_categories()
        self.refresh_group_list(listbox, selected_id)
        if self.categories:
            self.load_documents()

    def run_group_editor(self, parent, group=None):
        dialog = Gtk.Dialog(title=_("Group"),
                            transient_for=parent, modal=True, destroy_with_parent=True)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Save"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_default_size(560, 480)
        dialog.set_resizable(True)
        dialog.get_content_area().set_hexpand(True)
        dialog.get_content_area().set_vexpand(True)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=12)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        name_entry = Gtk.Entry()
        icon_button = XApp.IconChooserButton()
        icon_button.set_icon(group["icon"] if group else DEFAULT_GROUP_ICON)
        path_toggle = Gtk.CheckButton.new_with_label(_("Only include files in this folder"))
        path_button = Gtk.FileChooserButton(title=_("Choose a folder"),
                                            action=Gtk.FileChooserAction.SELECT_FOLDER)
        path_toggle.connect("toggled", lambda toggle: path_button.set_sensitive(toggle.get_active()))
        if group and group.get("path"):
            path_toggle.set_active(True)
            path_button.set_filename(group["path"])
        else:
            path_button.set_sensitive(False)
        type_store = Gtk.ListStore(str, str)
        if group:
            for mime_type in group["mime_types"]:
                type_store.append([mime_type, self.format_content_type(mime_type)])
        type_view = Gtk.TreeView(model=type_store, headers_visible=False)
        type_view.set_hexpand(True)
        type_view.set_vexpand(True)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("", renderer, text=1)
        type_view.append_column(column)
        type_scroll = Gtk.ScrolledWindow(min_content_height=120)
        type_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        type_scroll.set_shadow_type(Gtk.ShadowType.IN)
        type_scroll.set_hexpand(True)
        type_scroll.set_vexpand(True)
        type_scroll.add(type_view)
        type_frame = Gtk.Frame()
        type_frame.set_shadow_type(Gtk.ShadowType.IN)
        type_frame.set_hexpand(True)
        type_frame.set_vexpand(True)
        type_frame.add(type_scroll)
        type_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_type_button = self.create_icon_button("list-add-symbolic", _("Add"))
        remove_type_button = self.create_icon_button("list-remove-symbolic", _("Remove"))
        remove_type_button.set_sensitive(False)
        type_controls.pack_start(add_type_button, False, False, 0)
        type_controls.pack_start(remove_type_button, False, False, 0)
        type_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        type_box.set_hexpand(True)
        type_box.set_vexpand(True)
        hint = Gtk.Label(label=_("Choose files to add their types."), xalign=0)
        hint.get_style_context().add_class("dim-label")
        type_box.pack_start(hint, False, False, 0)
        type_box.pack_start(type_frame, True, True, 0)
        type_box.pack_start(type_controls, False, False, 0)
        add_type_button.connect("clicked", self.add_group_file_types, dialog, type_store)
        remove_type_button.connect("clicked", self.remove_group_file_type, type_view)
        type_view.get_selection().connect(
            "changed", lambda selection: remove_type_button.set_sensitive(
                selection.get_selected()[1] is not None))
        error_label = Gtk.Label(xalign=0)
        error_label.get_style_context().add_class("error")
        if group:
            name_entry.set_text(group["name"])
        grid.attach(Gtk.Label(label=_("Name"), xalign=1), 0, 0, 1, 1)
        grid.attach(name_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Icon"), xalign=1), 0, 1, 1, 1)
        grid.attach(icon_button, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label=_("File Types"), xalign=1, valign=Gtk.Align.START), 0, 2, 1, 1)
        grid.attach(type_box, 1, 2, 1, 1)
        grid.attach(path_toggle, 1, 3, 1, 1)
        grid.attach(path_button, 1, 4, 1, 1)
        grid.attach(error_label, 1, 5, 1, 1)
        dialog.get_content_area().pack_start(grid, True, True, 0)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            mime_types = [row[0] for row in type_store]
            name = name_entry.get_text().strip()
            path = path_button.get_filename() if path_toggle.get_active() else None
            if name and mime_types and (not path_toggle.get_active() or path):
                result = {
                    "id": group["id"] if group else uuid.uuid4().hex,
                    "name": name,
                    "icon": icon_button.get_icon() or DEFAULT_GROUP_ICON,
                    "mime_types": mime_types,
                    "path": path,
                }
                dialog.destroy()
                return result
            error_label.set_text(_("Enter a name, add at least one file type, and choose a folder if restricted."))
        dialog.destroy()
        return None

    def add_group_file_types(self, button, parent, type_store):
        chooser = Gtk.FileChooserDialog(title=_("Choose Example Files"),
                                        transient_for=parent,
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(_("Add"), Gtk.ResponseType.OK)
        chooser.set_select_multiple(True)
        if chooser.run() == Gtk.ResponseType.OK:
            existing = {row[0] for row in type_store}
            for filename in chooser.get_filenames():
                try:
                    info = Gio.File.new_for_path(filename).query_info(
                        "standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
                    mime_type = info.get_content_type()
                    if mime_type and mime_type not in existing:
                        type_store.append([mime_type, self.format_content_type(mime_type)])
                        existing.add(mime_type)
                except GLib.Error as e:
                    print("Could not determine file type: %s" % e)
        chooser.destroy()

    def remove_group_file_type(self, button, type_view):
        model, tree_iter = type_view.get_selection().get_selected()
        if tree_iter is not None:
            model.remove(tree_iter)

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_title(_("About"))
        dlg.set_program_name("thingy")
        dlg.set_comments(_("Library"))
        dlg.set_license_type(Gtk.License.GPL_3_0)
        dlg.set_version("__DEB_VERSION__")
        dlg.set_icon_name("thingy")
        dlg.set_logo_icon_name("thingy")
        dlg.set_website("https://www.github.com/linuxmint/thingy")
        def close(w, res):
            if res == Gtk.ResponseType.CANCEL or res == Gtk.ResponseType.DELETE_EVENT:
                w.destroy()
        dlg.connect("response", close)
        dlg.show()

    def on_menu_quit(self, widget):
        self.application.quit()

    def on_app_changed(self, widget, param):
        category_id = self.app_stack.get_visible_child_name()
        if (category_id in self.categories and
                category_id != self.groups_config.get("active_group")):
            self.groups_config["active_group"] = category_id
            self.save_groups_config()
        self.load_documents()

    @_async
    def load_documents(self, data=None):
        category_id = self.app_stack.get_visible_child_name()
        if category_id not in self.categories:
            return
        mime_types, path, self.flowbox, self.content_stack = self.categories[category_id]
        favorites_only = category_id == "favorites"
        self.documents = []
        self.clear_flowbox()

        # Favorites
        items = self.favorites_manager.get_favorites(None)
        for item in items:
            content_type = self.get_uri_content_type(item.uri, item.cached_mimetype)
            if (self.content_type_matches(content_type, mime_types) and
                    self.uri_is_in_path(item.uri, path)):
                self.add_document_to_library(item.uri, True)

        # Recent
        documents = []
        if not favorites_only:
            for recent in self.recent_manager.get_items():
                content_type = self.get_uri_content_type(recent.get_uri(), recent.get_mime_type())
                if (self.content_type_matches(content_type, mime_types) and
                        self.uri_is_in_path(recent.get_uri(), path)):
                    documents.append(recent)
        documents = sorted(documents, key=lambda x: x.get_modified(), reverse=True)
        for item in documents:
            self.add_document_to_library(item.get_uri(), False)

        self.set_stack_page()

    @staticmethod
    def content_type_matches(content_type, mime_types):
        if "*/*" in mime_types:
            return True
        if not content_type:
            return False
        return any(content_type == pattern or
                   (pattern.endswith("/*") and
                    content_type.startswith(pattern[:-1]))
                   for pattern in mime_types)

    @staticmethod
    def get_uri_content_type(uri, fallback=None):
        try:
            info = Gio.File.new_for_uri(uri).query_info(
                "standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
            return info.get_content_type() or fallback
        except GLib.Error:
            return fallback

    @staticmethod
    def uri_is_in_path(uri, path):
        if not path:
            return True
        file = Gio.File.new_for_uri(uri)
        if not file.is_native():
            return False
        try:
            document_path = os.path.realpath(file.get_path())
            group_path = os.path.realpath(path)
            return os.path.commonpath((document_path, group_path)) == group_path
        except (TypeError, ValueError):
            return False

    @idle
    def set_stack_page(self):
        if len(self.documents) > 0:
            self.content_stack.set_visible_child_name("page_documents")
        else:
            self.content_stack.set_visible_child_name("page_empty")

    @idle
    def clear_flowbox(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

    @idle
    def add_document_to_library(self, uri, mark_as_favorite):
        # Ignore duplicates
        real_path = os.path.realpath(uri)
        if real_path in self.documents:
            return
        f = Gio.File.new_for_uri(uri)
        # Ignore non-existing paths
        if not (f.is_native() and os.path.exists(f.get_path())):
            return
        info = f.query_info('*', Gio.FileQueryInfoFlags.NONE, None)
        self.documents.append(real_path)
        name = info.get_display_name()
        mtime = info.get_attribute_uint64("time::modified")
        thumbnail_path = (self.thumbnail_factory.lookup(f.get_uri(), mtime) or
                          info.get_attribute_byte_string ("thumbnail::path"))
        icon = info.get_attribute_object("standard::icon")
        current_page = info.get_attribute_string("metadata::xreader::page")
        num_pages = info.get_attribute_string("metadata::xreader::num-pages")
        epub_progress = info.get_attribute_string("metadata::xepub::progress")
        epub_title = info.get_attribute_string("metadata::xepub::title")
        epub_author = info.get_attribute_string("metadata::xepub::author")

        button = Gtk.Button()
        button.get_style_context().add_class("thingy-button")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_spacing(6)
        button.add(box)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(f.get_path())
        button.connect("button-press-event", self.on_button_pressed, uri, mark_as_favorite)
        label = Gtk.Label(label=epub_title or name)
        label.set_max_width_chars(25)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_halign(Gtk.Align.CENTER)

        author_label = None
        if epub_author:
            author_label = Gtk.Label(label=epub_author)
            author_label.set_max_width_chars(25)
            author_label.set_ellipsize(Pango.EllipsizeMode.END)
            author_label.set_halign(Gtk.Align.CENTER)
            author_label.get_style_context().add_class("dim-label")

        progress_tracked = False
        if epub_progress is not None:
            bar = Gtk.ProgressBar()
            bar.set_fraction(max(0.0, min(1.0, int(epub_progress) / 100.0)))
            bar.set_margin_start(50)
            bar.set_margin_end(50)
            box.pack_end(bar, False, False, 0)
            progress_tracked = True
        elif num_pages is not None and current_page is not None:
            num_pages = int(num_pages)
            if num_pages > 4:
                current_page = int(current_page)
                if current_page > 0:
                    progress = float(current_page) / float(num_pages - 1)
                    bar = Gtk.ProgressBar()
                    bar.set_fraction(progress)
                    bar.set_margin_start(50)
                    bar.set_margin_end(50)
                    box.pack_end(bar, False, False, 0)
                    progress_tracked = True

        if not progress_tracked:
            box.pack_end(Gtk.Label(), False, False, 0)

        if author_label:
            box.pack_end(author_label, False, False, 0)
        box.pack_end(label, False, False, 0)

        overlay = Gtk.Overlay()

        if thumbnail_path is not None:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(thumbnail_path, 198, 198)
        else:
            extension = os.path.splitext(uri)[1][1:].strip().lower()
            fallback_path = "/usr/share/thingy/doc-%s.svg" % extension
            if info.get_content_type().startswith("text/"):
                fallback_path = "/usr/share/thingy/doc-txt.svg"
            if os.path.exists(fallback_path):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(fallback_path, 198, 198)
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/thingy/doc.svg", 198, 198)

        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.get_style_context().add_class("thingy-image")

        if mark_as_favorite:
            emblem = Gtk.Image()
            emblem.set_from_icon_name("emblem-xapp-favorite", Gtk.IconSize.LARGE_TOOLBAR)
            emblem.set_halign(Gtk.Align.END)
            emblem.set_valign(Gtk.Align.START)
            emblem.set_margin_end(10)
            emblem.set_margin_top(10)
            overlay.add_overlay(emblem)

        image.set_halign(Gtk.Align.CENTER)
        overlay.add(image)
        overlay.set_halign(Gtk.Align.CENTER)
        box.pack_end(overlay, False, False, 0)

        self.flowbox.add(button)
        button.show_all()

    def on_button_pressed(self, widget, event, uri, is_favorite):
        if event.button == 1:
            self.open_document(widget, uri)
        elif event.button == 3:
            menu = Gtk.Menu()
            item = Gtk.MenuItem.new_with_label(_("Open"))
            item.connect("activate", self.open_document, uri)
            menu.add(item)
            item = Gtk.MenuItem.new_with_label(_("Open containing folder"))
            item.connect("activate", self.open_containing_folder, uri)
            menu.add(item)
            menu.add(Gtk.SeparatorMenuItem())
            if is_favorite:
                item = Gtk.MenuItem.new_with_label(_("Remove from favorites"))
                item.connect("activate", self.remove_favorite, uri)
            else:
                item = Gtk.MenuItem.new_with_label(_("Add to favorites"))
                item.connect("activate", self.add_favorite, uri)
            menu.add(item)
            item = Gtk.MenuItem.new_with_label(_("Remove from recent documents"))
            item.connect("activate", self.remove_from_recents, uri)
            item.set_sensitive(self.recent_manager.has_item(uri))
            menu.add(item)
            menu.add(Gtk.SeparatorMenuItem())
            item = Gtk.MenuItem.new_with_label(_("Move to trash"))
            item.connect("activate", self.trash, uri)
            menu.add(item)
            menu.show_all()
            menu.popup_at_pointer()

    @_async
    def trash(self, item, uri):
        subprocess.call(["gio", "trash", uri])
        self.load_documents()

    @_async
    def add_favorite(self, item, uri):
        try:
            self.favorites_manager.add(uri)
        except Exception as e:
            print(e)

    @_async
    def remove_favorite(self, item, uri):
        self.favorites_manager.remove(uri)

    def remove_from_recents(self, item, uri):
        try:
            self.recent_manager.remove_item(uri)
        except GLib.Error as e:
            print(e)

    @_async
    def open_document(self, item, uri):
        Gio.AppInfo.launch_default_for_uri(uri, None)

    @_async
    def open_containing_folder(self, item, uri):
        bus = Gio.Application.get_default().get_dbus_connection()
        file = Gio.File.new_for_uri(uri)

        if file.query_exists():
            startup_id = str(os.getpid())

            try:
                bus.call_sync("org.freedesktop.FileManager1",
                              "/org/freedesktop/FileManager1",
                              "org.freedesktop.FileManager1",
                              "ShowItems",
                              GLib.Variant("(ass)",
                                           ([uri], startup_id)),
                              None,
                              Gio.DBusCallFlags.NONE,
                              1000,
                              None)
                print("Opening containing folder using dbus")
                return
            except GLib.Error as e:
                pass

            try:
                print("Opening containing folder using Gio (mimetype)")
                parent_uri = file.get_parent().get_uri()
                Gio.AppInfo.launch_default_for_uri(parent_uri, None)
            except GLib.Error as e:
                print("Could not open containing folder: %s" % e.message)


if __name__ == "__main__":
    application = Application("org.x.thingy", Gio.ApplicationFlags.FLAGS_NONE)
    application.run()
