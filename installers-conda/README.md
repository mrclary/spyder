# Developing the conda-based Spyder installer

Since the conda-based installer creates a dedicated conda environment from which Spyder is run, using the standard development practices of bootstrapping from the local repository should be a faithful proxy for how the conda-based installer will behave.
However, some circumstances may require explicitly testing the conda-based application.
In this case, it is not necessary to make changes to the source code, then create the package installer, then reinstall Spyder.
It is sufficient to make changes to the source code then install from source directly to Spyder's dedicated conda environment.
Following are instructions for doing this.

1. If you have Spyder installed already as a standalone application (any flavor), and you don't want it clobbered, then rename Spyder.app to Spyder.bak.app (macOS) or something for Windows or something for Linux.
1. Install the experimental conda-based installer from link. If Spyder.app already exists (you didn't rename in previous step) then installation will fail and break the existing application.
2. Create a local clone of your forked Spyder repository, if you do not already have one.
3. Create a new branch. If this is development _of Spyder source code_, specifically for the conda-based installer and incompatible with the other installers, then branch off of the installers-conda-patch branch. Otherwise branch off of 5.x or master as appropriate.
4. Commit changes.
4. In a terminal, activate the conda-based Spyder environment
conda activate -p ~/Library/spyder-<ver>/envs/spyder-<ver>
or
source ~/Library/spyder-<ver>/bin/activate /Library/spyder-<ver>/envs/spyder-<ver>
5. Install Spyder from local source into Spyder's dedicated conda environment
python -m pip install .
