#!/usr/bin/env python
from fabric.api import settings, env
from celery import Celery
import os
import sys
import imp
import datetime
from redis import Redis

from gachette.lib.working_copy import WorkingCopy
from gachette.lib.stack import Stack

from operator import StackOperatorRedis
from garnison_api.backends import RedisBackend

# allow the usage of ssh config file by fabric
env.use_ssh_config = True
env.forward_agent = True
env.warn_only = True
# env.echo_stdin = False
env.always_use_pty = False

import pprint
pp = pprint.PrettyPrinter(indent=2)

# load config from file via environ variable
config = os.environ.get('GACHETTE_SETTINGS', './config.rc')
dd = imp.new_module('config')

with open(config) as config_file:
    dd.__file__ = config_file.name
    exec(compile(config_file.read(), config_file.name, 'exec'), dd.__dict__)

celery = Celery()
celery.add_defaults(dd)

# get settings
key_filename = None if not hasattr(dd, "BUILD_KEY_FILENAME") else dd.BUILD_KEY_FILENAME
host = dd.BUILD_HOST

# TODO REMOVE - FOR EASY TESTING
if not RedisBackend().get_domain("main"):
    RedisBackend().create_domain("main")
if not RedisBackend().get_domain("main")["available_packages"]:
    RedisBackend().update_domain("main", available_packages=["test_config", "test_application"])

def send_notification(data):
    """
    Send notification using Pubsub Redis
    """
    red = Redis(dd.REDIS_HOST, int(dd.REDIS_PORT))
    red.publish("all", ['publish', data])

@celery.task
def package_build_process(name, url, branch, path_to_missile=None,
                          domain=None, stack=None):
    """
    Prepare working copy, checkout working copy, build
    """
    logfilename = "build-%s-%s-%s.log" % (name, branch, datetime.datetime.utcnow().isoformat())
    logfilepath = os.path.join(dd.BUILD_LOGPATH, logfilename)
    sys.stdout = open(logfilepath, "w")
    sys.stderr = sys.stdout

    args = ["name", "url", "branch", "path_to_missile"]
    for arg in args:
        print arg , ": ", locals()[arg]

    with settings(host_string=host, key_filename=key_filename):
        wc = WorkingCopy(name, base_folder="/var/gachette")
        wc.prepare_environment()
        wc.checkout_working_copy(url=url, branch=branch)

        latest_version = RedisBackend().get_latest_version(name)
        new_base_version = RedisBackend().get_new_base_version(name)
        new_version = wc.get_version_from_git(base_version=new_base_version)
        # skipping existing build removed
        new_version += "-%s" % branch
        wc.set_version(app=new_version, env=new_version, service=new_version)
        result = wc.build(output_path="/var/gachette/debs", path_to_missile=path_to_missile)
        RedisBackend().delete_lock("packages", name)
        RedisBackend().create_package(name, new_version, result)
        print "Built new:", name, branch, new_version

    if domain is not None and stack is not None:
        RedisBackend().add_stack_package(domain, stack, name, new_version)
        print "Added to 'domains:%s:stacks:%s:packages' as {'%s': '%s'}" % (domain, stack, name, new_version)

@celery.task
def add_package_to_stack_process(domain, stack, name, version, file_name):
    """
    Add built package to the stack.
    """
    with settings(host_string=host, key_filename=key_filename):
        s = Stack(domain, stack, meta_path="/var/gachette/", operator=StackOperatorRedis(redis_host=dd.REDIS_HOST))
        s.add_package(name, version=version, file_name=file_name)
