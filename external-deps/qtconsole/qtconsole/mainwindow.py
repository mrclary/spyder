"""The Qt MainWindow for the QtConsole

This is a tabbed pseudo-terminal of Jupyter sessions, with a menu bar for
common actions.
"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import sys
import webbrowser
from functools import partial
from threading import Thread

from jupyter_core.paths import jupyter_runtime_dir
from pygments.styles import get_all_styles

from qtpy import QtGui, QtCore, QtWidgets
from qtconsole import styles
from qtconsole.jupyter_widget import JupyterWidget
from qtconsole.usage import gui_reference


def background(f):
    """call a function in a simple thread, to prevent blocking"""
    t = Thread(target=f)
    t.start()
    return t


class MainWindow(QtWidgets.QMainWindow):

    #---------------------------------------------------------------------------
    # 'object' interface
    #---------------------------------------------------------------------------

    def __init__(self, app,
                    confirm_exit=True,
                    new_frontend_factory=None, slave_frontend_factory=None,
                    connection_frontend_factory=None,
                    parent=None
                ):
        """ Create a tabbed MainWindow for managing FrontendWidgets

        Parameters
        ----------

        app : reference to QApplication parent
        confirm_exit : bool, optional
            Whether we should prompt on close of tabs
        new_frontend_factory : callable
            A callable that returns a new JupyterWidget instance, attached to
            its own running kernel.
        slave_frontend_factory : callable
            A callable that takes an existing JupyterWidget, and  returns a new
            JupyterWidget instance, attached to the same kernel.
        """

        super().__init__(parent=parent)
        self._kernel_counter = 0
        self._external_kernel_counter = 0
        self._app = app
        self.confirm_exit = confirm_exit
        self.new_frontend_factory = new_frontend_factory
        self.slave_frontend_factory = slave_frontend_factory
        self.connection_frontend_factory = connection_frontend_factory

        self.tab_widget = QtWidgets.QTabWidget(self)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested[int].connect(self.close_tab)

        self.setCentralWidget(self.tab_widget)
        # hide tab bar at first, since we have no tabs:
        self.tab_widget.tabBar().setVisible(False)
        # prevent focus in tab bar
        self.tab_widget.setFocusPolicy(QtCore.Qt.NoFocus)

    def update_tab_bar_visibility(self):
        """ update visibility of the tabBar depending of the number of tab

        0 or 1 tab, tabBar hidden
        2+ tabs, tabBar visible

        send a self.close if number of tab ==0

        need to be called explicitly, or be connected to tabInserted/tabRemoved
        """
        if self.tab_widget.count() <= 1:
            self.tab_widget.tabBar().setVisible(False)
        else:
            self.tab_widget.tabBar().setVisible(True)
        if self.tab_widget.count()==0 :
            self.close()

    @property
    def next_kernel_id(self):
        """constantly increasing counter for kernel IDs"""
        c = self._kernel_counter
        self._kernel_counter += 1
        return c

    @property
    def next_external_kernel_id(self):
        """constantly increasing counter for external kernel IDs"""
        c = self._external_kernel_counter
        self._external_kernel_counter += 1
        return c

    @property
    def active_frontend(self):
        return self.tab_widget.currentWidget()

    def create_tab_with_new_frontend(self):
        """create a new frontend and attach it to a new tab"""
        widget = self.new_frontend_factory()
        self.add_tab_with_frontend(widget)

    def set_window_title(self):
        """Set the title of the console window"""
        old_title = self.windowTitle()
        title, ok = QtWidgets.QInputDialog.getText(self,
                                                   "Rename Window",
                                                   "New title:",
                                                   text=old_title)
        if ok:
            self.setWindowTitle(title)

    def create_tab_with_existing_kernel(self):
        """create a new frontend attached to an external kernel in a new tab"""
        connection_file, file_type = QtWidgets.QFileDialog.getOpenFileName(self,
                                                     "Connect to Existing Kernel",
                                                     jupyter_runtime_dir(),
                                                     "Connection file (*.json)")
        if not connection_file:
            return
        widget = self.connection_frontend_factory(connection_file)
        name = "external {}".format(self.next_external_kernel_id)
        self.add_tab_with_frontend(widget, name=name)

    def create_tab_with_current_kernel(self):
        """create a new frontend attached to the same kernel as the current tab"""
        current_widget = self.tab_widget.currentWidget()
        current_widget_index = self.tab_widget.indexOf(current_widget)
        current_widget_name = self.tab_widget.tabText(current_widget_index)
        widget = self.slave_frontend_factory(current_widget)
        if 'slave' in current_widget_name:
            # don't keep stacking slaves
            name = current_widget_name
        else:
            name = '(%s) slave' % current_widget_name
        self.add_tab_with_frontend(widget,name=name)

    def set_tab_title(self):
        """Set the title of the current tab"""
        old_title = self.tab_widget.tabText(self.tab_widget.currentIndex())
        title, ok = QtWidgets.QInputDialog.getText(self,
                                                   "Rename Tab",
                                                   "New title:",
                                                   text=old_title)
        if ok:
            self.tab_widget.setTabText(self.tab_widget.currentIndex(), title)

    def close_tab(self,current_tab):
        """ Called when you need to try to close a tab.

        It takes the number of the tab to be closed as argument, or a reference
        to the widget inside this tab
        """

        # let's be sure "tab" and "closing widget" are respectively the index
        # of the tab to close and a reference to the frontend to close
        if type(current_tab) is not int :
            current_tab = self.tab_widget.indexOf(current_tab)
        closing_widget=self.tab_widget.widget(current_tab)


        # when trying to be closed, widget might re-send a request to be
        # closed again, but will be deleted when event will be processed. So
        # need to check that widget still exists and skip if not. One example
        # of this is when 'exit' is sent in a slave tab. 'exit' will be
        # re-sent by this function on the master widget, which ask all slave
        # widgets to exit
        if closing_widget is None:
            return

        #get a list of all slave widgets on the same kernel.
        slave_tabs = self.find_slave_widgets(closing_widget)

        keepkernel = None #Use the prompt by default
        if hasattr(closing_widget,'_keep_kernel_on_exit'): #set by exit magic
            keepkernel = closing_widget._keep_kernel_on_exit
            # If signal sent by exit magic (_keep_kernel_on_exit, exist and not None)
            # we set local slave tabs._hidden to True to avoid prompting for kernel
            # restart when they get the signal. and then "forward" the 'exit'
            # to the main window
            if keepkernel is not None:
                for tab in slave_tabs:
                    tab._hidden = True
                if closing_widget in slave_tabs:
                    try :
                        self.find_master_tab(closing_widget).execute('exit')
                    except AttributeError:
                        self.log.info("Master already closed or not local, closing only current tab")
                        self.tab_widget.removeTab(current_tab)
                    self.update_tab_bar_visibility()
                    return

        kernel_client = closing_widget.kernel_client
        kernel_manager = closing_widget.kernel_manager

        if keepkernel is None and not closing_widget._confirm_exit:
            # don't prompt, just terminate the kernel if we own it
            # or leave it alone if we don't
            keepkernel = closing_widget._existing
        if keepkernel is None: #show prompt
            if kernel_client and kernel_client.channels_running:
                title = self.window().windowTitle()
                cancel = QtWidgets.QMessageBox.Cancel
                okay = QtWidgets.QMessageBox.Ok
                if closing_widget._may_close:
                    msg = "You are closing the tab : "+'"'+self.tab_widget.tabText(current_tab)+'"'
                    info = "Would you like to quit the Kernel and close all attached Consoles as well?"
                    justthis = QtWidgets.QPushButton("&No, just this Tab", self)
                    justthis.setShortcut('N')
                    closeall = QtWidgets.QPushButton("&Yes, close all", self)
                    closeall.setShortcut('Y')
                    # allow ctrl-d ctrl-d exit, like in terminal
                    closeall.setShortcut('Ctrl+D')
                    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question,
                                            title, msg)
                    box.setInformativeText(info)
                    box.addButton(cancel)
                    box.addButton(justthis, QtWidgets.QMessageBox.NoRole)
                    box.addButton(closeall, QtWidgets.QMessageBox.YesRole)
                    box.setDefaultButton(closeall)
                    box.setEscapeButton(cancel)
                    pixmap = QtGui.QPixmap(self._app.icon.pixmap(QtCore.QSize(64,64)))
                    box.setIconPixmap(pixmap)
                    reply = box.exec_()
                    if reply == 1: # close All
                        for slave in slave_tabs:
                            background(slave.kernel_client.stop_channels)
                            self.tab_widget.removeTab(self.tab_widget.indexOf(slave))
                        kernel_manager.shutdown_kernel()
                        self.tab_widget.removeTab(current_tab)
                        background(kernel_client.stop_channels)
                    elif reply == 0: # close Console
                        if not closing_widget._existing:
                            # Have kernel: don't quit, just close the tab
                            closing_widget.execute("exit True")
                        self.tab_widget.removeTab(current_tab)
                        background(kernel_client.stop_channels)
                else:
                    reply = QtWidgets.QMessageBox.question(self, title,
                        "Are you sure you want to close this Console?"+
                        "\nThe Kernel and other Consoles will remain active.",
                        okay|cancel,
                        defaultButton=okay
                        )
                    if reply == okay:
                        self.tab_widget.removeTab(current_tab)
        elif keepkernel: #close console but leave kernel running (no prompt)
            self.tab_widget.removeTab(current_tab)
            background(kernel_client.stop_channels)
        else: #close console and kernel (no prompt)
            self.tab_widget.removeTab(current_tab)
            if kernel_client and kernel_client.channels_running:
                for slave in slave_tabs:
                    background(slave.kernel_client.stop_channels)
                    self.tab_widget.removeTab(self.tab_widget.indexOf(slave))
                if kernel_manager:
                    kernel_manager.shutdown_kernel()
                background(kernel_client.stop_channels)

        self.update_tab_bar_visibility()

    def add_tab_with_frontend(self,frontend,name=None):
        """ insert a tab with a given frontend in the tab bar, and give it a name

        """
        if not name:
            name = 'kernel %i' % self.next_kernel_id
        self.tab_widget.addTab(frontend,name)
        self.update_tab_bar_visibility()
        self.make_frontend_visible(frontend)
        frontend.exit_requested.connect(self.close_tab)

    def next_tab(self):
        self.tab_widget.setCurrentIndex((self.tab_widget.currentIndex()+1))

    def prev_tab(self):
        self.tab_widget.setCurrentIndex((self.tab_widget.currentIndex()-1))

    def make_frontend_visible(self,frontend):
        widget_index=self.tab_widget.indexOf(frontend)
        if widget_index > 0 :
            self.tab_widget.setCurrentIndex(widget_index)

    def find_master_tab(self,tab,as_list=False):
        """
        Try to return the frontend that owns the kernel attached to the given widget/tab.

            Only finds frontend owned by the current application. Selection
            based on port of the kernel might be inaccurate if several kernel
            on different ip use same port number.

            This function does the conversion tabNumber/widget if needed.
            Might return None if no master widget (non local kernel)
            Will crash if more than 1 masterWidget

            When asList set to True, always return a list of widget(s) owning
            the kernel. The list might be empty or containing several Widget.
        """

        #convert from/to int/richIpythonWidget if needed
        if isinstance(tab, int):
            tab = self.tab_widget.widget(tab)
        km=tab.kernel_client

        #build list of all widgets
        widget_list = [self.tab_widget.widget(i) for i in range(self.tab_widget.count())]

        # widget that are candidate to be the owner of the kernel does have all the same port of the curent widget
        # And should have a _may_close attribute
        filtered_widget_list = [ widget for widget in widget_list if
                                widget.kernel_client.connection_file == km.connection_file and
                                hasattr(widget,'_may_close') ]
        # the master widget is the one that may close the kernel
        master_widget= [ widget for widget in filtered_widget_list if widget._may_close]
        if as_list:
            return master_widget
        assert(len(master_widget)<=1 )
        if len(master_widget)==0:
            return None

        return master_widget[0]

    def find_slave_widgets(self,tab):
        """return all the frontends that do not own the kernel attached to the given widget/tab.

            Only find frontends owned by the current application. Selection
            based on connection file of the kernel.

            This function does the conversion tabNumber/widget if needed.
        """
        #convert from/to int/richIpythonWidget if needed
        if isinstance(tab, int):
            tab = self.tab_widget.widget(tab)
        km=tab.kernel_client

        #build list of all widgets
        widget_list = [self.tab_widget.widget(i) for i in range(self.tab_widget.count())]

        # widget that are candidate not to be the owner of the kernel does have all the same port of the curent widget
        filtered_widget_list = ( widget for widget in widget_list if
                                widget.kernel_client.connection_file == km.connection_file)
        # Get a list of all widget owning the same kernel and removed it from
        # the previous cadidate. (better using sets ?)
        master_widget_list = self.find_master_tab(tab, as_list=True)
        slave_list = [widget for widget in filtered_widget_list if widget not in master_widget_list]

        return slave_list

    # Populate the menu bar with common actions and shortcuts
    def add_menu_action(self, menu, action, defer_shortcut=False):
        """Add action to menu as well as self

        So that when the menu bar is invisible, its actions are still available.

        If defer_shortcut is True, set the shortcut context to widget-only,
        where it will avoid conflict with shortcuts already bound to the
        widgets themselves.
        """
        menu.addAction(action)
        self.addAction(action)

        if defer_shortcut:
            action.setShortcutContext(QtCore.Qt.WidgetShortcut)

    def init_menu_bar(self):
        #create menu in the order they should appear in the menu bar
        self.init_file_menu()
        self.init_edit_menu()
        self.init_view_menu()
        self.init_kernel_menu()
        self.init_window_menu()
        self.init_help_menu()

    def init_file_menu(self):
        self.file_menu = self.menuBar().addMenu("&File")

        self.new_kernel_tab_act = QtWidgets.QAction("New Tab with &New kernel",
            self,
            shortcut="Ctrl+T",
            triggered=self.create_tab_with_new_frontend)
        self.add_menu_action(self.file_menu, self.new_kernel_tab_act)

        self.slave_kernel_tab_act = QtWidgets.QAction("New Tab with Sa&me kernel",
            self,
            shortcut="Ctrl+Shift+T",
            triggered=self.create_tab_with_current_kernel)
        self.add_menu_action(self.file_menu, self.slave_kernel_tab_act)

        self.existing_kernel_tab_act = QtWidgets.QAction("New Tab with &Existing kernel",
                                                     self,
                                                     shortcut="Alt+T",
                                                     triggered=self.create_tab_with_existing_kernel)
        self.add_menu_action(self.file_menu, self.existing_kernel_tab_act)

        self.file_menu.addSeparator()

        self.close_action=QtWidgets.QAction("&Close Tab",
            self,
            shortcut=QtGui.QKeySequence.Close,
            triggered=self.close_active_frontend
            )
        self.add_menu_action(self.file_menu, self.close_action)

        self.export_action=QtWidgets.QAction("&Save to HTML/XHTML",
            self,
            shortcut=QtGui.QKeySequence.Save,
            triggered=self.export_action_active_frontend
            )
        self.add_menu_action(self.file_menu, self.export_action, True)

        self.file_menu.addSeparator()

        printkey = QtGui.QKeySequence(QtGui.QKeySequence.Print)
        if printkey.matches("Ctrl+P") and sys.platform != 'darwin':
            # Only override the default if there is a collision.
            # Qt ctrl = cmd on OSX, so the match gets a false positive on OSX.
            printkey = "Ctrl+Shift+P"
        self.print_action = QtWidgets.QAction("&Print",
            self,
            shortcut=printkey,
            triggered=self.print_action_active_frontend)
        self.add_menu_action(self.file_menu, self.print_action, True)

        if sys.platform != 'darwin':
            # OSX always has Quit in the Application menu, only add it
            # to the File menu elsewhere.

            self.file_menu.addSeparator()

            self.quit_action = QtWidgets.QAction("&Quit",
                self,
                shortcut=QtGui.QKeySequence.Quit,
                triggered=self.close,
            )
            self.add_menu_action(self.file_menu, self.quit_action)


    def init_edit_menu(self):
        self.edit_menu = self.menuBar().addMenu("&Edit")

        self.undo_action = QtWidgets.QAction("&Undo",
            self,
            shortcut=QtGui.QKeySequence.Undo,
            statusTip="Undo last action if possible",
            triggered=self.undo_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.undo_action)

        self.redo_action = QtWidgets.QAction("&Redo",
            self,
            shortcut=QtGui.QKeySequence.Redo,
            statusTip="Redo last action if possible",
            triggered=self.redo_active_frontend)
        self.add_menu_action(self.edit_menu, self.redo_action)

        self.edit_menu.addSeparator()

        self.cut_action = QtWidgets.QAction("&Cut",
            self,
            shortcut=QtGui.QKeySequence.Cut,
            triggered=self.cut_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.cut_action, True)

        self.copy_action = QtWidgets.QAction("&Copy",
            self,
            shortcut=QtGui.QKeySequence.Copy,
            triggered=self.copy_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.copy_action, True)

        self.copy_raw_action = QtWidgets.QAction("Copy (&Raw Text)",
            self,
            shortcut="Ctrl+Shift+C",
            triggered=self.copy_raw_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.copy_raw_action, True)

        self.paste_action = QtWidgets.QAction("&Paste",
            self,
            shortcut=QtGui.QKeySequence.Paste,
            triggered=self.paste_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.paste_action, True)

        self.edit_menu.addSeparator()

        selectall = QtGui.QKeySequence(QtGui.QKeySequence.SelectAll)
        if selectall.matches("Ctrl+A") and sys.platform != 'darwin':
            # Only override the default if there is a collision.
            # Qt ctrl = cmd on OSX, so the match gets a false positive on OSX.
            selectall = "Ctrl+Shift+A"
        self.select_all_action = QtWidgets.QAction("Select Cell/&All",
            self,
            shortcut=selectall,
            triggered=self.select_all_active_frontend
            )
        self.add_menu_action(self.edit_menu, self.select_all_action, True)


    def init_view_menu(self):
        self.view_menu = self.menuBar().addMenu("&View")

        if sys.platform != 'darwin':
            # disable on OSX, where there is always a menu bar
            self.toggle_menu_bar_act = QtWidgets.QAction("Toggle &Menu Bar",
                self,
                shortcut="Ctrl+Shift+M",
                statusTip="Toggle visibility of menubar",
                triggered=self.toggle_menu_bar)
            self.add_menu_action(self.view_menu, self.toggle_menu_bar_act)

        fs_key = "Ctrl+Meta+F" if sys.platform == 'darwin' else "F11"
        self.full_screen_act = QtWidgets.QAction("&Full Screen",
            self,
            shortcut=fs_key,
            statusTip="Toggle between Fullscreen and Normal Size",
            triggered=self.toggleFullScreen)
        self.add_menu_action(self.view_menu, self.full_screen_act)

        self.view_menu.addSeparator()

        self.increase_font_size = QtWidgets.QAction("Zoom &In",
            self,
            shortcut=QtGui.QKeySequence.ZoomIn,
            triggered=self.increase_font_size_active_frontend
            )
        self.add_menu_action(self.view_menu, self.increase_font_size, True)

        self.decrease_font_size = QtWidgets.QAction("Zoom &Out",
            self,
            shortcut=QtGui.QKeySequence.ZoomOut,
            triggered=self.decrease_font_size_active_frontend
            )
        self.add_menu_action(self.view_menu, self.decrease_font_size, True)

        self.reset_font_size = QtWidgets.QAction("Zoom &Reset",
            self,
            shortcut="Ctrl+0",
            triggered=self.reset_font_size_active_frontend
            )
        self.add_menu_action(self.view_menu, self.reset_font_size, True)

        self.view_menu.addSeparator()

        self.clear_action = QtWidgets.QAction("&Clear Screen",
            self,
            shortcut='Ctrl+L',
            statusTip="Clear the console",
            triggered=self.clear_active_frontend)
        self.add_menu_action(self.view_menu, self.clear_action)

        self.completion_menu = self.view_menu.addMenu("&Completion type")

        completion_group = QtWidgets.QActionGroup(self)
        active_frontend_completion = self.active_frontend.gui_completion
        ncurses_completion_action = QtWidgets.QAction(
            "&ncurses",
            self,
            triggered=lambda: self.set_completion_widget_active_frontend(
                'ncurses'))
        ncurses_completion_action.setCheckable(True)
        ncurses_completion_action.setChecked(
            active_frontend_completion == 'ncurses')
        droplist_completion_action = QtWidgets.QAction(
            "&droplist",
            self,
            triggered=lambda: self.set_completion_widget_active_frontend(
                'droplist'))
        droplist_completion_action.setCheckable(True)
        droplist_completion_action.setChecked(
            active_frontend_completion == 'droplist')
        plain_commpletion_action = QtWidgets.QAction(
            "&plain",
            self,
            triggered=lambda: self.set_completion_widget_active_frontend(
                'plain'))
        plain_commpletion_action.setCheckable(True)
        plain_commpletion_action.setChecked(
            active_frontend_completion == 'plain')

        completion_group.addAction(ncurses_completion_action)
        completion_group.addAction(droplist_completion_action)
        completion_group.addAction(plain_commpletion_action)

        self.completion_menu.addAction(ncurses_completion_action)
        self.completion_menu.addAction(droplist_completion_action)
        self.completion_menu.addAction(plain_commpletion_action)
        self.completion_menu.setDefaultAction(ncurses_completion_action)

        self.pager_menu = self.view_menu.addMenu("&Pager")

        hsplit_action = QtWidgets.QAction(".. &Horizontal Split",
            self,
            triggered=lambda: self.set_paging_active_frontend('hsplit'))

        vsplit_action = QtWidgets.QAction(" : &Vertical Split",
            self,
            triggered=lambda: self.set_paging_active_frontend('vsplit'))

        inside_action = QtWidgets.QAction("   &Inside Pager",
            self,
            triggered=lambda: self.set_paging_active_frontend('inside'))

        self.pager_menu.addAction(hsplit_action)
        self.pager_menu.addAction(vsplit_action)
        self.pager_menu.addAction(inside_action)

        available_syntax_styles = self.get_available_syntax_styles()
        if len(available_syntax_styles) > 0:
            self.syntax_style_menu = self.view_menu.addMenu("&Syntax Style")
            style_group = QtWidgets.QActionGroup(self)
            for style in available_syntax_styles:
                action = QtWidgets.QAction("{}".format(style), self)
                action.triggered.connect(partial(self.set_syntax_style,
                                                 style))
                action.setCheckable(True)
                style_group.addAction(action)
                self.syntax_style_menu.addAction(action)
                if style == 'default':
                    action.setChecked(True)
                    self.syntax_style_menu.setDefaultAction(action)

    def init_kernel_menu(self):
        self.kernel_menu = self.menuBar().addMenu("&Kernel")
        # Qt on OSX maps Ctrl to Cmd, and Meta to Ctrl
        # keep the signal shortcuts to ctrl, rather than
        # platform-default like we do elsewhere.

        ctrl = "Meta" if sys.platform == 'darwin' else "Ctrl"

        self.interrupt_kernel_action = QtWidgets.QAction("&Interrupt current Kernel",
            self,
            triggered=self.interrupt_kernel_active_frontend,
            shortcut=ctrl+"+C",
            )
        self.add_menu_action(self.kernel_menu, self.interrupt_kernel_action)

        self.restart_kernel_action = QtWidgets.QAction("&Restart current Kernel",
            self,
            triggered=self.restart_kernel_active_frontend,
            shortcut=ctrl+"+.",
            )
        self.add_menu_action(self.kernel_menu, self.restart_kernel_action)

        self.kernel_menu.addSeparator()

        self.confirm_restart_kernel_action = QtWidgets.QAction("&Confirm kernel restart",
            self,
            checkable=True,
            checked=self.active_frontend.confirm_restart,
            triggered=self.toggle_confirm_restart_active_frontend
            )

        self.add_menu_action(self.kernel_menu, self.confirm_restart_kernel_action)
        self.tab_widget.currentChanged.connect(self.update_restart_checkbox)

    def init_window_menu(self):
        self.window_menu = self.menuBar().addMenu("&Window")
        if sys.platform == 'darwin':
            # add min/maximize actions to OSX, which lacks default bindings.
            self.minimizeAct = QtWidgets.QAction("Mini&mize",
                self,
                shortcut="Ctrl+m",
                statusTip="Minimize the window/Restore Normal Size",
                triggered=self.toggleMinimized)
            # maximize is called 'Zoom' on OSX for some reason
            self.maximizeAct = QtWidgets.QAction("&Zoom",
                self,
                shortcut="Ctrl+Shift+M",
                statusTip="Maximize the window/Restore Normal Size",
                triggered=self.toggleMaximized)

            self.add_menu_action(self.window_menu, self.minimizeAct)
            self.add_menu_action(self.window_menu, self.maximizeAct)
            self.window_menu.addSeparator()

        prev_key = "Ctrl+Alt+Left" if sys.platform == 'darwin' else "Ctrl+PgUp"
        self.prev_tab_act = QtWidgets.QAction("Pre&vious Tab",
            self,
            shortcut=prev_key,
            statusTip="Select previous tab",
            triggered=self.prev_tab)
        self.add_menu_action(self.window_menu, self.prev_tab_act)

        next_key = "Ctrl+Alt+Right" if sys.platform == 'darwin' else "Ctrl+PgDown"
        self.next_tab_act = QtWidgets.QAction("Ne&xt Tab",
            self,
            shortcut=next_key,
            statusTip="Select next tab",
            triggered=self.next_tab)
        self.add_menu_action(self.window_menu, self.next_tab_act)

        self.rename_window_act = QtWidgets.QAction("Rename &Window",
                                               self,
                                               shortcut="Alt+R",
                                               statusTip="Rename window",
                                               triggered=self.set_window_title)
        self.add_menu_action(self.window_menu, self.rename_window_act)


        self.rename_current_tab_act = QtWidgets.QAction("&Rename Current Tab",
                                                    self,
                                                    shortcut="Ctrl+R",
                                                    statusTip="Rename current tab",
                                                    triggered=self.set_tab_title)
        self.add_menu_action(self.window_menu, self.rename_current_tab_act)

    def init_help_menu(self):
        # please keep the Help menu in Mac Os even if empty. It will
        # automatically contain a search field to search inside menus and
        # please keep it spelled in English, as long as Qt Doesn't support
        # a QAction.MenuRole like HelpMenuRole otherwise it will lose
        # this search field functionality
        self.help_menu = self.menuBar().addMenu("&Help")

        # Help Menu
        self.help_action = QtWidgets.QAction("Show &QtConsole help", self,
                                         triggered=self._show_help)
        self.online_help_action = QtWidgets.QAction("Open online &help", self,
                                                triggered=self._open_online_help)
        self.add_menu_action(self.help_menu, self.help_action)
        self.add_menu_action(self.help_menu, self.online_help_action)

    def _set_active_frontend_focus(self):
        # this is a hack, self.active_frontend._control seems to be
        # a private member. Unfortunately this is the only method
        # to set focus reliably
        QtCore.QTimer.singleShot(200, self.active_frontend._control.setFocus)

    # minimize/maximize/fullscreen actions:

    def toggle_menu_bar(self):
        menu_bar = self.menuBar()
        if menu_bar.isVisible():
            menu_bar.setVisible(False)
        else:
            menu_bar.setVisible(True)

    def toggleMinimized(self):
        if not self.isMinimized():
            self.showMinimized()
        else:
            self.showNormal()

    def _show_help(self):
        self.active_frontend._page(gui_reference)

    def _open_online_help(self):
        webbrowser.open("https://qtconsole.readthedocs.io", new=1, autoraise=True)

    def toggleMaximized(self):
        if not self.isMaximized():
            self.showMaximized()
        else:
            self.showNormal()

    # Min/Max imizing while in full screen give a bug
    # when going out of full screen, at least on OSX
    def toggleFullScreen(self):
        if not self.isFullScreen():
            self.showFullScreen()
            if sys.platform == 'darwin':
                self.maximizeAct.setEnabled(False)
                self.minimizeAct.setEnabled(False)
        else:
            self.showNormal()
            if sys.platform == 'darwin':
                self.maximizeAct.setEnabled(True)
                self.minimizeAct.setEnabled(True)

    def set_paging_active_frontend(self, paging):
        self.active_frontend._set_paging(paging)

    def set_completion_widget_active_frontend(self, gui_completion):
        self.active_frontend._set_completion_widget(gui_completion)

    def get_available_syntax_styles(self):
        """Get a list with the syntax styles available."""
        styles = list(get_all_styles())
        return sorted(styles)

    def set_syntax_style(self, syntax_style):
        """Set up syntax style for the current console."""
        if syntax_style=='bw':
            colors='nocolor'
        elif styles.dark_style(syntax_style):
            colors='linux'
            
        else:
            colors='lightbg'
        self.active_frontend.syntax_style = syntax_style
        style_sheet = styles.sheet_from_template(syntax_style, colors)
        self.active_frontend.style_sheet = style_sheet
        self.active_frontend._syntax_style_changed()
        self.active_frontend._style_sheet_changed()
        self.active_frontend.reset(clear=True)
        self.active_frontend._execute(
f"""
from IPython.core.ultratb import VerboseTB
if getattr(VerboseTB, 'tb_highlight_style', None) is not None:
    VerboseTB.tb_highlight_style = '{syntax_style}'
elif getattr(VerboseTB, '_tb_highlight_style', None) is not None:
    VerboseTB._tb_highlight_style = '{syntax_style}'
else:
    get_ipython().run_line_magic('colors', '{colors}')
""",
            True)
        

    def close_active_frontend(self):
        self.close_tab(self.active_frontend)

    def restart_kernel_active_frontend(self):
        self.active_frontend.request_restart_kernel()

    def interrupt_kernel_active_frontend(self):
        self.active_frontend.request_interrupt_kernel()

    def toggle_confirm_restart_active_frontend(self):
        widget = self.active_frontend
        widget.confirm_restart = not widget.confirm_restart
        self.confirm_restart_kernel_action.setChecked(widget.confirm_restart)

    def update_restart_checkbox(self):
        if self.active_frontend is None:
            return
        widget = self.active_frontend
        self.confirm_restart_kernel_action.setChecked(widget.confirm_restart)

    def clear_active_frontend(self):
        self.active_frontend.clear()

    def cut_active_frontend(self):
        widget = self.active_frontend
        if widget.can_cut():
            widget.cut()

    def copy_active_frontend(self):
        widget = self.active_frontend
        widget.copy()

    def copy_raw_active_frontend(self):
        self.active_frontend._copy_raw_action.trigger()

    def paste_active_frontend(self):
        widget = self.active_frontend
        if widget.can_paste():
            widget.paste()

    def undo_active_frontend(self):
        self.active_frontend.undo()

    def redo_active_frontend(self):
        self.active_frontend.redo()

    def print_action_active_frontend(self):
        self.active_frontend.print_action.trigger()

    def export_action_active_frontend(self):
        self.active_frontend.export_action.trigger()

    def select_all_active_frontend(self):
        self.active_frontend.select_all_action.trigger()

    def increase_font_size_active_frontend(self):
        self.active_frontend.increase_font_size.trigger()

    def decrease_font_size_active_frontend(self):
        self.active_frontend.decrease_font_size.trigger()

    def reset_font_size_active_frontend(self):
        self.active_frontend.reset_font_size.trigger()

    #---------------------------------------------------------------------------
    # QWidget interface
    #---------------------------------------------------------------------------

    def closeEvent(self, event):
        """ Forward the close event to every tabs contained by the windows
        """
        if self.tab_widget.count() == 0:
            # no tabs, just close
            event.accept()
            return
        # Do Not loop on the widget count as it change while closing
        title = self.window().windowTitle()
        cancel = QtWidgets.QMessageBox.Cancel
        okay = QtWidgets.QMessageBox.Ok
        accept_role = QtWidgets.QMessageBox.AcceptRole

        if self.confirm_exit:
            if self.tab_widget.count() > 1:
                msg = "Close all tabs, stop all kernels, and Quit?"
            else:
                msg = "Close console, stop kernel, and Quit?"
            info = "Kernels not started here (e.g. notebooks) will be left alone."
            closeall = QtWidgets.QPushButton("&Quit", self)
            closeall.setShortcut('Q')
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question,
                                    title, msg)
            box.setInformativeText(info)
            box.addButton(cancel)
            box.addButton(closeall, QtWidgets.QMessageBox.YesRole)
            box.setDefaultButton(closeall)
            box.setEscapeButton(cancel)
            pixmap = QtGui.QPixmap(self._app.icon.pixmap(QtCore.QSize(64,64)))
            box.setIconPixmap(pixmap)
            reply = box.exec_()
        else:
            reply = okay

        if reply == cancel:
            event.ignore()
            return
        if reply == okay or reply == accept_role:
            while self.tab_widget.count() >= 1:
                # prevent further confirmations:
                widget = self.active_frontend
                widget._confirm_exit = False
                self.close_tab(widget)
            event.accept()
