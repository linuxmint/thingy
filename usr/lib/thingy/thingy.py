#!/usr/bin/python3
import gettext
import gi
import locale
import os
import setproctitle
import subprocess
import threading
gi.require_version('Gtk', '3.0')
gi.require_version('XApp', '1.0')
from gi.repository import Gtk, Gio, GLib, XApp, Pango, GdkPixbuf, Gdk

setproctitle.setproctitle("thingy")

# i18n
APP = 'thingy'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

XREADER_MIME_TYPES = ['application/pdf', 'application/x-bzpdf', 'application/x-gzpdf', 'application/x-xzpdf', \
'application/postscript', 'application/x-bzpostscript', 'application/x-gzpostscript', 'image/x-eps', 'image/x-bzeps', \
'image/x-gzeps', 'application/x-dvi', 'application/x-bzdvi', 'application/x-gzdvi', 'image/vnd.djvu', \
'image/vnd.djvu+multipage', 'image/tiff', 'application/x-cbr', 'application/x-cbz', 'application/x-cb7', \
'application/x-cbt', 'application/vnd.comicbook+zip', 'application/vnd.comicbook-rar', 'application/oxps', \
'application/vnd.ms-xpsdocument', 'application/epub+zip']

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

        self.recent_manager = Gtk.RecentManager()
        self.favorites_manager = XApp.Favorites.get_default()

        # Set the Glade file
        gladefile = "/usr/share/thingy/thingy.ui"
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file(gladefile)
        self.window = self.builder.get_object("main_window")
        self.window.set_title(_("Library"))
        XApp.set_window_icon_name (self.window, "thingy")

        # Menubar
        accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(accel_group)
        menu = self.builder.get_object("main_menu")
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

        self.flowbox = self.builder.get_object("flowbox")

        # Preserve window state
        self.width = self.settings.get_int("width")
        self.height = self.settings.get_int("height")
        self.maximized = self.settings.get_boolean("maximized")
        self.window.resize(self.width, self.height)
        if self.maximized:
            self.window.maximize()
        else:
            self.window.resize(self.width, self.height)

        self.window.connect("size-allocate", self.on_window_resized)
        self.window.connect("window-state-event", self.on_window_state_changed)
        self.window.connect("destroy", self.on_window_destroyed)

        # Load data
        self.app_mime_types = XREADER_MIME_TYPES
        for app_info in Gio.AppInfo.get_all():
            if app_info.get_filename() == "/usr/share/applications/xreader.desktop":
                self.app_mime_types = app_info.get_supported_types()

        self.load_documents()

        self.recent_manager.connect("changed", self.load_documents)
        self.favorites_manager.connect("changed", self.load_documents)

    def on_window_resized(self, window, allocation):
        self.width = allocation.width
        self.height = allocation.height

    def on_window_state_changed(self, window, event):
        self.maximized = window.get_window().get_state() & Gdk.WindowState.MAXIMIZED == Gdk.WindowState.MAXIMIZED

    def on_window_destroyed(self, window):
        self.settings.set_int("width", self.width)
        self.settings.set_int("height", self.height)
        self.settings.set_boolean("maximized", self.maximized)

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_title(_("About"))
        dlg.set_program_name("thingy")
        dlg.set_comments(_("Library"))
        try:
            h = open('/usr/share/common-licenses/GPL', encoding="utf-8")
            s = h.readlines()
            gpl = ""
            for line in s:
                gpl += line
            h.close()
            dlg.set_license(gpl)
        except Exception as e:
            print (e)

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

    @_async
    def load_documents(self, data=None):
        self.documents = []
        self.clear_flowbox()

        # Favorites
        items = self.favorites_manager.get_favorites(None)
        for item in items:
            if item.cached_mimetype in self.app_mime_types:
                uri = item.uri
                f = Gio.File.new_for_uri(uri)
                if f.is_native() and os.path.exists(f.get_path()):
                    info = f.query_info('*', Gio.FileQueryInfoFlags.NONE, None)
                    self.add_document_to_library(info, uri, True)

        # Recent
        documents = []
        for recent in self.recent_manager.get_items():
            if recent.get_mime_type() in self.app_mime_types:
                documents.append(recent)
        documents = sorted(documents, key=lambda x: x.get_modified(), reverse=True)
        for item in documents:
            uri = item.get_uri()
            if item.is_local() and item.exists():
                f = Gio.File.new_for_uri(uri)
                info = f.query_info('*', Gio.FileQueryInfoFlags.NONE, None)
                self.add_document_to_library(info, uri, False)

        self.set_stack_page()

    @idle
    def set_stack_page(self):
        if len(self.documents) > 0:
            self.builder.get_object("stack").set_visible_child_name("page_documents")
        else:
            self.builder.get_object("stack").set_visible_child_name("page_empty")

    @idle
    def clear_flowbox(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

    @idle
    def add_document_to_library(self, info, uri, mark_as_favorite):
        if uri in self.documents:
            return
        self.documents.append(uri)
        name = info.get_display_name()
        thumbnail_path = info.get_attribute_byte_string ("thumbnail::path")
        icon = info.get_attribute_object("standard::icon")
        current_page = info.get_attribute_string("metadata::xreader::page")
        num_pages = info.get_attribute_string("metadata::xreader::num-pages")

        button = Gtk.Button()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_spacing(6)
        button.add(box)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(name)
        button.connect("button-press-event", self.on_button_pressed, uri, mark_as_favorite)
        label = Gtk.Label(label=name)
        label.set_max_width_chars(25)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_halign(Gtk.Align.CENTER)

        progress_tracked = False
        if (num_pages != None and current_page != None):
            num_pages = int(num_pages)
            current_page = int(current_page)
            if current_page > 0:
                progress = float(current_page) / float(num_pages)
                bar = Gtk.ProgressBar()
                bar.set_fraction(progress)
                bar.set_margin_start(50)
                bar.set_margin_end(50)
                box.pack_end(bar, False, False, 0)
                progress_tracked = True

        if not progress_tracked:
            box.pack_end(Gtk.Label(), False, False, 0)

        box.pack_end(label, False, False, 0)

        overlay = Gtk.Overlay()

        if thumbnail_path != None:
            image = Gtk.Image.new_from_file(thumbnail_path)
        else:
            extension = os.path.splitext(uri)[1][1:].strip().lower()
            if os.path.exists("/usr/share/thingy/doc-%s.svg" % extension):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/thingy/doc-%s.svg" % extension, 198, 256)
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/thingy/doc.svg", 198, 256)
            image = Gtk.Image.new_from_pixbuf(pixbuf)

        if mark_as_favorite:
            emblem = Gtk.Image()
            emblem.set_from_icon_name("emblem-xapp-favorite", Gtk.IconSize.LARGE_TOOLBAR)
            emblem.set_halign(Gtk.Align.END)
            emblem.set_valign(Gtk.Align.START)
            emblem.set_margin_end(30)
            emblem.set_margin_top(10)
            overlay.add_overlay(emblem)

        overlay.add(image)
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

    @_async
    def open_document(self, item, uri):
        subprocess.Popen(["xreader", uri])

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

        app = Gio.AppInfo.get_default_for_type("inode/directory", True)

        try:
            print("Opening containing folder using Gio (mimetype)")
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as e:
            print("Could not open containing folder: %s" % e.message)


if __name__ == "__main__":
    application = Application("org.x.thingy", Gio.ApplicationFlags.FLAGS_NONE)
    application.run()

