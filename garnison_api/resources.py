import json

from flask import Flask, request
from flask.ext.restful import Resource, abort, reqparse

from gachette_web.tasks2 import package_build_process

from .backends import RedisBackend

PROJECTS_DATA = {
    'test_config': {
        'repo': 'git@github.com:ops-hero/test_config.git',
        'path_to_missile': None
    },
    'test_application': {
        'repo': 'git@github.com:ops-hero/test_application.git',
        'path_to_missile': None
    },
}

class DomainList(Resource):
    def get(self):
        return {"domains": RedisBackend().list_domains()}
    def post(self):
        abort(405)

class Domain(Resource):
    def get(self, domain):
        domain = RedisBackend().get_domain(domain)
        return domain if domain else abort(404)

    def put(self, domain):  # TODO maybe POST?
        try:
            RedisBackend().create_domain(domain)
            return {"status": 201, "message": "Created"}
        except TypeError as e:
            print e
            abort(400)

class StackList(Resource):
    def get(self, domain):
        return {"stacks": RedisBackend().list_stacks(domain)}

class Stack(Resource):

    def get(self, domain, stack):
        stack = RedisBackend().get_stack(domain, stack)
        return stack if stack else abort(404)

    def put(self, domain, stack):
        try:
            RedisBackend().create_stack(domain, stack)
            # TODO add package setup
            return {"status": 201, "message": "Created"}
        except TypeError as e:
            print e
            abort(400)

class Build(Resource):
    def __init__(self, *args, **kwargs):
        super(Resource, self).__init__(*args, **kwargs)
        self.reqparse = reqparse.RequestParser()

    def put(self, project):
        self.reqparse.add_argument("domain", type=str)
        self.reqparse.add_argument("stack", type=str)
        args = self.reqparse.parse_args()
        domain, stack = args["domain"], args["stack"]
        
        if domain and stack:
            if not RedisBackend().stack_exists(domain, stack):
                abort(404)
        if project not in PROJECTS_DATA:
            abort(400)
        try:
            RedisBackend().create_lock("packages", project)
        except TypeError as e:
            print e
            abort(409, status=409, message="Conflict", info="Build in progress")
        package_build_process.delay(project, PROJECTS_DATA[project]["repo"],
                              "master", "1",
                              path_to_missile=PROJECTS_DATA[project]["path_to_missile"],
                              domain=domain, stack=stack)

    def post(self, project):
        print request.get_json()

    def get(self, project):
        print project

class LockList(Resource):
    def __init__(self, *args, **kwargs):
        super(Resource, self).__init__(*args, **kwargs)
        self.reqparse = reqparse.RequestParser()

    def get(self):
        return {"locks": RedisBackend().list_locks()}

    def delete(self):
        self.reqparse.add_argument("type", type=str)
        self.reqparse.add_argument("name", type=str)
        args = self.reqparse.parse_args()
        type_, name = args["type"], args["name"]
        RedisBackend().delete_lock(type_, name)
        return {"status": 200, "message": "Ok"}



RESOURCES = [
    (DomainList, "/api/domains/"),
    (Domain, "/api/domains/<string:domain>"),
    (StackList, "/api/domains/<string:domain>/stacks/"),
    (Stack, "/api/domains/<string:domain>/stacks/<string:stack>"),
    (Build, "/api/builds/<string:project>"),
    (LockList, "/api/locks/"),
]

def add_resources(api):
    for resource in RESOURCES:
        api.add_resource(*resource)

