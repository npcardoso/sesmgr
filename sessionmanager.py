import gtk
import subprocess
import signal
import os
import shlex
import threading
import sys
from datetime import datetime
import time
import logging 

FORMAT = '%(asctime)-15s|%(name)-10s|%(message)s'
logging.basicConfig(format=FORMAT, level = logging.INFO)

class Application(object):
    def __init__(self, application, dialog=True, retries=1, interval=1, stdout=None, stderr=None):
        self.__logger = logging.getLogger("App: '%s'" % application)
        self.__application = application
        self.__dialog = dialog
        self.__retries = retries
        self.__interval = interval
        self.reset()
        
        if stdout is None:
            stdout = '/dev/null'
        self.__logger.info("Opening '%s' for stdout" % stdout)
        self.__stdout = open(stdout, 'a', 0)
        
        if stderr is None:
            stderr = '/dev/null'
        self.__logger.info("Opening '%s' for stderr" % stderr)
        self.__stderr = open(stderr, 'a', 0)


    def reset(self):
        self.__process = None
        if self.__retries:
            self.__persist = True
        else:
            self.__persist = False
        self.__last_launch = self.__retries * [0]

    def __str__(self):
        return self.__application

    @staticmethod
    def __time():
        now = datetime.now()
        return float(now.strftime('%s.%f'))

    def launch(self):
        try:
            self.__logger.info("Launching")
            self.__process = p = subprocess.Popen(self.__application, shell=True, stdout=self.__stdout, stderr=self.__stderr)
            if self.__retries:
                self.__last_launch = self.__last_launch[1:] + [self.__time()]
            self.__logger.info("Launched")
            return p.pid
        except OSError:
            return False

    def relaunch(self, when=None):
        if not self.__persist:
            return 0
        if when is None:
            when = self.__time()

        t = when - self.__interval
        if self.__last_launch[0] < t:
            return 1
        return -1

    def kill(self, sig):
        self.__persist = False
        if self.__process is None:
            return False
        try:
            if os.waitpid(self.__process.pid,os.WNOHANG)[0] != 0:
                return False
            self.__logger.info("Killing %s, pid: %d with sig: %d" % (self.__application, self.__process.pid, sig))
            os.kill(self.__process.pid, sig)
        except OSError:
            return False
        return True



class Session(object):
    def __launch(self, app):
        pid = app.launch()
        if pid is False:
            print "Could not launch '%s'"  % str(app)
        else:
            with self.__waiter_notifier:
                self.__pids[pid] = app
                self.__waiter_notifier.notify_all()

    def __finish(self, sig, _):
        logger = logging.getLogger("Finisher")
        logger.info("Cleaning Up")
        logger.info("Disabling Signals")
        for sig in self.__sigs:
            signal.signal(sig, signal.SIG_IGN)

        pids = self.__pids
        logger.info("Soft Kiling")
        for app in pids.values():
            logger.info("Signalling '%s'" % str(app))
            app.kill(signal.SIGINT)
        
        logger.info("Waiting grace time(%ss)" % self.__kill_grace_time)
        time.sleep(self.__kill_grace_time)
        logger.info("Hard Kiling")
        for app in pids.values():
            logger.info("Signalling '%s'" % str(app))
            app.kill(signal.SIGKILL)
        logger.info("Finished")
        sys.exit(0)


    def __waiter(self):
        logger = logging.getLogger("Waiter")
        logger.info("Ready!")
        while self.__active:
            try:
                logger.info("Waiting for child")
                status = os.wait()
                logger.info("Got it: %d" % status[0])
                with self.__lock:
                    logger.info("Got Lock. Processing..")
                    pids = self.__pids
                    app = pids[status[0]]
                    del pids[status[0]]
                    logger.info("'%s' (%d) Exited; Notifying!" % (str(app), status[0]))
                    now = datetime.now()
                    self.__events.append((app, float(now.strftime('%s.%f'))))
                    self.__lock.notify_all()
            except OSError:
                logger.info("Got OSError while waiting for children")
                with self.__waiter_notifier:
                    self.__waiter_notifier.wait()
        logger.info("Finished!")

    def __message_box(self, app):
        with self.__message_box_lock:
            dialog = gtk.Dialog("Relaunch?", None, 0,
                                (gtk.STOCK_NO, gtk.RESPONSE_NO,
                                 gtk.STOCK_YES, gtk.RESPONSE_YES))
            label = gtk.Label("'%s' Stopped working. Relaunch?" % str(app))
            label.show()
            dialog.set_keep_above(True)
            dialog.get_content_area().add(label)
            response = dialog.run()
            dialog.destroy()
            while gtk.events_pending():
                gtk.main_iteration(False)

        if response == gtk.RESPONSE_YES:
            return 1
        return 0

    def __relauncher(self, app, app_str, relaunch):
        logger = logging.getLogger("Relauncher")
        if relaunch == -1:
            # Ask user to relaunch
            relaunch = self.__message_box(app_str)
            if relaunch:
                logger.info("User selected relaunch")
                with self.__lock:
                    app.reset()
        
        if relaunch == 1:
            logger.info("Relaunch '%s'" % app_str)
            with self.__lock:
                self.__launch(app)
        else:
            self.__active -= 1
            logger.info("Removing '%s'; Still active: %d" % (app_str, self.__active))

    def __executor(self):
        logger = logging.getLogger("Executor")
        logger.info("Ready!")

        while True:
            with self.__lock:
                if not self.__active:
                    logger.info("No active applications left; exiting.")
                    os.kill(os.getpid(), signal.SIGHUP)
                    return
                logger.info("Event Queue: %s %r" % (str(self.__events), not self.__events))
                if not self.__events:
                    logger.info("Waiting for event")
                    self.__lock.wait()
                (app, time) = self.__events.pop(0)
                logger.info("Got Event: %s @ %f" % (app, time))
                relaunch = app.relaunch(time)
                app_str = str(app)
            launcher = threading.Thread(target=self.__relauncher, args=(app, app_str, relaunch))
            launcher.daemon = True
            launcher.start()
            


    def __init__(self, applications, kill_grace_time=1):
        gtk.gdk.threads_init()
        self.__message_box_lock = threading.Condition()
        self.__waiter_notifier = threading.Condition()
        self.__lock = threading.Condition()
        logger = logging.getLogger("Session")
        self.__kill_grace_time = kill_grace_time
        self.__events = []
        self.__pids = {}
        self.__applications = applications
        self.__active = len(applications)

        self.__sigs = [signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, 
                signal.SIGILL, signal.SIGABRT, 
                signal.SIGFPE, signal.SIGSEGV]
                              
        for sig in self.__sigs:
            signal.signal(sig, self.__finish)

        logger.info("Initial app launch")
        with self.__lock:
            for app in self.__applications:
                self.__launch(app)

        executor = threading.Thread(target=self.__executor)
        executor.daemon = True
        executor.start()

        waiter = threading.Thread(target=self.__waiter)
        waiter.daemon = True
        waiter.start()
        
        while True:
            time.sleep(10000);

def makeApps(configs, defaults, log_dir):
    apps = []

    for app in configs:
        app_def = defaults
        if log_dir is not None:
            app_def += (os.path.join(log_dir, app[0] + ".stdout"), os.path.join(log_dir, app[0] + ".stderr"))
        apps.append(Application(*(app[0] + " " +  app[1], ) + app[2:] + app_def[len(app) - 2:]))
    return apps
