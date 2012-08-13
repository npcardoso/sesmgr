sesmgr
======

SesMgr is an application designed to create a sessions and kill launched applications on exit.
Additionally, it relaunches applications when they exit.

Example
-------
The session definition is done by means of a python file, such as for instance:


    #!/usr/bin/env python2
	from sessionmanager import Application, Session, makeApps

  	configs = (
    #Format: (application, dialog, retries, interval, stdout, stderr)
		("openbox", ""),
		("xfce4-panel", "", False, 0),

	#Visual Stuff
		("unclutter", -idle 5"),
		("xcompmgr", "-c -s -fF -n -I 0.4 -D 5")
		)


	defaults = (True, 1, 1)
	Session(makeApps(configs, defaults, log_dir=None))
