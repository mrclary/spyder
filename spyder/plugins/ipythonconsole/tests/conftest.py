# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © Spyder Project Contributors
#
# Licensed under the terms of the MIT License
# ----------------------------------------------------------------------------

# Standard library imports
import os
import os.path as osp
from pathlib import Path
import sys
import threading
import traceback
from unittest.mock import Mock

# Third-party imports
import psutil
from pygments.token import Name
import pytest
from qtpy.QtWidgets import QMainWindow
from spyder_kernels.utils.style import create_style_class

# Local imports
from spyder.api.plugins import Plugins
from spyder.app.cli_options import get_options
from spyder.config.gui import get_color_scheme
from spyder.config.manager import CONF
from spyder.plugins.debugger.plugin import Debugger
from spyder.plugins.help.utils.sphinxify import CSS_PATH
from spyder.plugins.ipythonconsole.plugin import IPythonConsole
from spyder.utils.conda import get_list_conda_envs


# =============================================================================
# ---- Constants
# =============================================================================
SHELL_TIMEOUT = 40000 if os.name == 'nt' else 20000
NEW_DIR = 'new_workingdir'
PY312_OR_GREATER = sys.version_info[:2] >= (3, 12)


# =============================================================================
# ---- Pytest adjustments
# =============================================================================
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    setattr(item, "rep_" + rep.when, rep)


# =============================================================================
# ---- Utillity Functions
# =============================================================================
def get_console_font_color(syntax_style):
    styles = create_style_class(get_color_scheme(syntax_style)).styles
    font_color = styles[Name]
    return font_color


def get_console_background_color(style_sheet):
    background_color = style_sheet.split('background-color:')[1]
    background_color = background_color.split(';')[0]
    return background_color


def get_conda_test_env():
    """
    Return the full prefix path of the env used to test kernel activation and
    its executable.
    """
    # Get conda env to use
    test_env_executable = get_list_conda_envs()['Conda: spytest-ž'][0]

    # Get the env prefix
    if os.name == 'nt':
        test_env_prefix = osp.dirname(test_env_executable)
    else:
        test_env_prefix = osp.dirname(osp.dirname(test_env_executable))

    return (test_env_prefix, test_env_executable)


# =============================================================================
# ---- Fixtures
# =============================================================================
@pytest.fixture
def ipyconsole(qtbot, request, tmpdir):
    """IPython console fixture."""
    configuration = CONF
    no_web_widgets = request.node.get_closest_marker('no_web_widgets')

    class MainWindowMock(QMainWindow):

        def __init__(self):
            # This avoids using the cli options passed to pytest
            sys_argv = [sys.argv[0]]
            self._cli_options = get_options(sys_argv)[0]
            if no_web_widgets:
                self._cli_options.no_web_widgets = True
            super().__init__()

        def __getattr__(self, attr):
            if attr == 'consoles_menu_actions':
                return []
            elif attr == 'editor':
                return None
            else:
                return Mock()

    # Tests assume inline backend
    configuration.set('ipython_console', 'pylab/backend', 'inline')

    # Start the console in a fixed working directory
    use_startup_wdir = request.node.get_closest_marker('use_startup_wdir')
    if use_startup_wdir:
        new_wdir = str(tmpdir.mkdir(NEW_DIR))
        configuration.set(
            'workingdir',
            'startup/use_project_or_home_directory',
            False
        )
        configuration.set('workingdir', 'startup/use_fixed_directory', True)
        configuration.set('workingdir', 'startup/fixed_directory', new_wdir)
    else:
        configuration.set(
            'workingdir',
            'startup/use_project_or_home_directory',
            True
        )
        configuration.set('workingdir', 'startup/use_fixed_directory', False)

    # Use the automatic backend if requested
    auto_backend = request.node.get_closest_marker('auto_backend')
    if auto_backend:
        configuration.set('ipython_console', 'pylab/backend', 'auto')

    # Use the Tkinter backend if requested
    tk_backend = request.node.get_closest_marker('tk_backend')
    if tk_backend:
        configuration.set('ipython_console', 'pylab/backend', 'tk')

    # Start a Pylab client if requested
    pylab_client = request.node.get_closest_marker('pylab_client')
    special = "pylab" if pylab_client else None

    # Start a Sympy client if requested
    sympy_client = request.node.get_closest_marker('sympy_client')
    special = "sympy" if sympy_client else special

    # Start a Cython client if requested
    cython_client = request.node.get_closest_marker('cython_client')
    special = "cython" if cython_client else special

    # Start a specific env client if requested
    environment_client = request.node.get_closest_marker(
        'environment_client')
    given_name = None
    path_to_custom_interpreter = None
    if environment_client:
        given_name = 'spytest-ž'
        path_to_custom_interpreter = get_conda_test_env()[1]

    # Use an external interpreter if requested
    external_interpreter = request.node.get_closest_marker(
        'external_interpreter')
    if external_interpreter:
        configuration.set('main_interpreter', 'default', False)
        configuration.set('main_interpreter', 'executable', sys.executable)
    else:
        configuration.set('main_interpreter', 'default', True)
        configuration.set('main_interpreter', 'executable', '')

    # Use the test environment interpreter if requested
    test_environment_interpreter = request.node.get_closest_marker(
        'test_environment_interpreter')
    if test_environment_interpreter:
        configuration.set('main_interpreter', 'default', False)
        configuration.set(
            'main_interpreter', 'executable', get_conda_test_env()[1])
    else:
        configuration.set('main_interpreter', 'default', True)
        configuration.set('main_interpreter', 'executable', '')

    # Conf css_path in the Appeareance plugin
    configuration.set('appearance', 'css_path', CSS_PATH)

    # Create the console and a new client and set environment
    os.environ['IPYCONSOLE_TESTING'] = 'True'
    window = MainWindowMock()
    console = IPythonConsole(parent=window, configuration=configuration)

    # connect to a debugger plugin
    debugger = Debugger(parent=window, configuration=configuration)

    def get_plugin(name):
        if name == Plugins.IPythonConsole:
            return console
        return None

    debugger.get_plugin = get_plugin
    debugger.on_ipython_console_available()

    # Plugin setup
    console.on_initialize()
    console._register()
    console.get_widget().matplotlib_status.register_ipythonconsole(console)

    # Register handlers to run cells.
    def get_file_code(fname, save_all=True):
        """
        Get code from a file.

        save_all is necessary to keep consistency with the handler registered
        in the editor.
        """
        path = Path(fname)
        return path.read_text()

    def get_cell(cell_id, fname):
        """
        Get cell code from a file.

        For now this only works with unnamed cells and cell separators of the
        form `# %%`.
        """
        path = Path(fname)
        contents = path.read_text()
        cells = contents.split("# %%")
        return cells[int(cell_id)]

    console.register_spyder_kernel_call_handler('get_file_code', get_file_code)
    console.register_spyder_kernel_call_handler('run_cell', get_cell)

    # Start client and show window
    console.create_new_client(
        special=special,
        given_name=given_name,
        path_to_custom_interpreter=path_to_custom_interpreter
    )
    window.setCentralWidget(console.get_widget())

    if os.name == 'nt':
        qtbot.addWidget(window)

    with qtbot.waitExposed(window):
        window.resize(640, 480)
        window.show()

    # Set exclamation mark to True
    configuration.set('debugger', 'pdb_use_exclamation_mark', True)

    # Create new client for Matplotlb backend tests
    if auto_backend or tk_backend:
        qtbot.wait(SHELL_TIMEOUT)
        console.create_new_client()

    # Wait until the window is fully up
    qtbot.waitUntil(lambda: console.get_current_shellwidget() is not None)
    shell = console.get_current_shellwidget()
    try:
        if test_environment_interpreter:
            # conda version is not always up to date, so a version warning
            # might be displayed, so shell.spyder_kernel_ready will not be True
            qtbot.waitUntil(
                lambda: shell._prompt_html is not None,
                timeout=SHELL_TIMEOUT)
        else:
            qtbot.waitUntil(
                lambda: (
                    shell.spyder_kernel_ready
                    and shell._prompt_html is not None
                ),
                timeout=SHELL_TIMEOUT)
    except Exception:
        # Print content of shellwidget and close window
        print(console.get_current_shellwidget()._control.toPlainText())
        client = console.get_current_client()
        if client.info_page != client.blank_page:
            print('info_page')
            print(client.info_page)
        raise

    # Check for thread or open file leaks
    known_leak = request.node.get_closest_marker('known_leak')

    if os.name != 'nt' and not known_leak:
        # _DummyThread are created if current_thread() is called from them.
        # They will always leak (From python doc) so we ignore them.
        init_threads = [
            repr(thread) for thread in threading.enumerate()
            if not isinstance(thread, threading._DummyThread)]
        proc = psutil.Process()
        init_files = [repr(f) for f in proc.open_files()]
        init_subprocesses = [repr(f) for f in proc.children()]

    yield console

    # Print shell content if failed
    if request.node.rep_setup.passed:
        if request.node.rep_call.failed:
            # Print content of shellwidget and close window
            print(console.get_current_shellwidget()._control.toPlainText())
            client = console.get_current_client()
            if client.info_page != client.blank_page:
                print('info_page')
                print(client.info_page)

    # Close
    console.on_close()
    os.environ.pop('IPYCONSOLE_TESTING')

    if os.name == 'nt' or known_leak:
        # Do not test for leaks
        return

    def show_diff(init_list, now_list, name):
        sys.stderr.write(f"Extra {name} before test:\n")
        for item in init_list:
            if item in now_list:
                now_list.remove(item)
            else:
                sys.stderr.write(item + "\n")
        sys.stderr.write(f"Extra {name} after test:\n")
        for item in now_list:
            sys.stderr.write(item + "\n")

    # The test is not allowed to open new files or threads.
    try:
        def threads_condition():
            threads = [
                thread for thread in threading.enumerate()
                if not isinstance(thread, threading._DummyThread)]
            return (len(init_threads) >= len(threads))

        qtbot.waitUntil(threads_condition, timeout=SHELL_TIMEOUT)
    except Exception:
        now_threads = [
            thread for thread in threading.enumerate()
            if not isinstance(thread, threading._DummyThread)]
        threads = [repr(t) for t in now_threads]
        show_diff(init_threads, threads, "thread")
        sys.stderr.write("Running Threads stacks:\n")
        now_thread_ids = [t.ident for t in now_threads]
        for thread_id, frame in sys._current_frames().items():
            if thread_id in now_thread_ids:
                sys.stderr.write("\nThread " + str(threads) + ":\n")
                traceback.print_stack(frame)
        raise

    try:
        # -1 from closed client
        qtbot.waitUntil(lambda: (
            len(init_subprocesses) - 1 >= len(proc.children())),
            timeout=SHELL_TIMEOUT)
    except Exception:
        subprocesses = [repr(f) for f in proc.children()]
        show_diff(init_subprocesses, subprocesses, "processes")
        raise

    try:
        qtbot.waitUntil(
            lambda: (len(init_files) >= len(proc.open_files())),
            timeout=SHELL_TIMEOUT)
    except Exception:
        files = [repr(f) for f in proc.open_files()]
        show_diff(init_files, files, "files")
        raise


@pytest.fixture
def mpl_rc_file(tmp_path):
    """Create matplotlibrc file"""
    file_contents = """
figure.dpi: 99
figure.figsize: 9, 9
figure.subplot.bottom: 0.9
font.size: 9
"""
    rc_file = str(tmp_path / 'matplotlibrc')
    with open(rc_file, 'w') as f:
        f.write(file_contents)
    os.environ['MATPLOTLIBRC'] = rc_file

    yield

    os.environ.pop('MATPLOTLIBRC')
    os.remove(rc_file)
