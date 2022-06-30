# -*- coding: utf8 -*-
"""
.. module:: burpui.api.settings
    :platform: Unix
    :synopsis: Burp-UI settings api module.

.. moduleauthor:: Ziirish <ziirish@ziirish.info>

"""
import sys

# This is a submodule we can also use "from ..api import api"
from . import api
from flask.ext.restplus import reqparse, abort, Resource
from flask.ext.login import current_user, login_required
from flask import jsonify, request, url_for
from werkzeug.datastructures import ImmutableMultiDict
if sys.version_info >= (3, 0):
    from urllib.parse import unquote
else:
    from urllib import unquote


@api.resource('/api/settings/server-config',
              '/api/<server>/settings/server-config',
              '/api/settings/server-config/<path:conf>',
              '/api/<server>/settings/server-config/<path:conf>',
              endpoint='api.server_settings')
class ServerSettings(Resource):
    """The :class:`burpui.api.settings.ServerSettings` resource allows you to
    read and write the server's configuration.

    This resource is part of the :mod:`burpui.api.settings` module.
    """

    @login_required
    def post(self, conf=None, server=None):
        noti = api.bui.cli.store_conf_srv(request.form, conf, server)
        return {'notif': noti}, 200

    @login_required
    def get(self, conf=None, server=None):
        """**GET** method provided by the webservice.

        The *JSON* returned is:
        ::

            {
              "boolean": [
                "daemon",
                "fork",
                "..."
              ],
              "defaults": {
                "address": "",
                "autoupgrade_dir": "",
                "ca_burp_ca": "",
                "ca_conf": "",
                "ca_name": "",
                "ca_server_name": "",
                "client_can_delete": true,
                "...": "..."
              },
              "integer": [
                "port",
                "status_port",
                "..."
              ],
              "multi": [
                "keep",
                "restore_client",
                "..."
              ],
              "placeholders": {
                "autoupgrade_dir": "path",
                "ca_burp_ca": "path",
                "ca_conf": "path",
                "ca_name": "name",
                "ca_server_name": "name",
                "client_can_delete": "0|1",
                "...": "..."
              },
              "results": {
                "boolean": [
                  {
                    "name": "hardlinked_archive",
                    "value": false
                  },
                  {
                    "name": "syslog",
                    "value": true
                  },
                  { "...": "..." }
                ],
                "clients": [
                  {
                    "name": "testclient",
                    "value": "/etc/burp/clientconfdir/testclient"
                  }
                ],
                "common": [
                  {
                    "name": "mode",
                    "value": "server"
                  },
                  {
                    "name": "directory",
                    "value": "/var/spool/burp"
                  },
                  { "...": "..." }
                ],
                "includes": [],
                "includes_ext": [],
                "integer": [
                  {
                    "name": "port",
                    "value": 4971
                  },
                  {
                    "name": "status_port",
                    "value": 4972
                  },
                  { "...": "..." }
                ],
                "multi": [
                  {
                    "name": "keep",
                    "value": [
                      "7",
                      "4"
                    ]
                  },
                  { "...": "..." }
                ]
              },
              "server_doc": {
                "address": "Defines the main TCP address that the server listens on. The default is either '::' or '0.0.0.0', dependent upon compile time options.",
                "...": "..."
              },
              "string": [
                "mode",
                "address",
                "..."
              ],
              "suggest": {
                "compression": [
                  "gzip1",
                  "gzip2",
                  "gzip3",
                  "gzip4",
                  "gzip5",
                  "gzip6",
                  "gzip7",
                  "gzip8",
                  "gzip9"
                ],
                "mode": [
                  "client",
                  "server"
                ],
                "...": []
              }
            }


        :param server: Which server to collect data from when in multi-agent mode
        :type server: str

        :returns: The *JSON* described above.
        """
        # Only the admin can edit the configuration
        if (api.bui.acl and not
                api.bui.acl.is_admin(current_user.get_id())):
            abort(403, message='Sorry, you don\'t have rights to access the setting panel')

        try:
            conf = unquote(conf)
        except:
            pass
        r = api.bui.cli.read_conf_srv(conf, server)
        return jsonify(results=r,
                       boolean=api.bui.cli.get_parser_attr('boolean_srv', server),
                       string=api.bui.cli.get_parser_attr('string_srv', server),
                       integer=api.bui.cli.get_parser_attr('integer_srv', server),
                       multi=api.bui.cli.get_parser_attr('multi_srv', server),
                       server_doc=api.bui.cli.get_parser_attr('doc', server),
                       suggest=api.bui.cli.get_parser_attr('values', server),
                       placeholders=api.bui.cli.get_parser_attr('placeholders', server),
                       defaults=api.bui.cli.get_parser_attr('defaults', server))


@api.resource('/api/settings/clients.json',
              '/api/<server>/settings/clients.json',
              endpoint='api.clients_list')
class ClientsList(Resource):

    @login_required
    def get(self, server=None):
        res = api.bui.cli.clients_list(server)
        return jsonify(result=res)


@api.resource('/api/settings/<client>/client-config',
              '/api/settings/<client>/client-config/<path:conf>',
              '/api/<server>/settings/<client>/client-config',
              '/api/<server>/settings/<client>/client-config/<path:conf>',
              endpoint='api.client_settings')
class ClientSettings(Resource):

    @login_required
    def post(self, server=None, client=None, conf=None):
        noti = api.bui.cli.store_conf_cli(request.form, client, conf, server)
        return jsonify(notif=noti)

    @login_required
    def get(self, server=None, client=None, conf=None):
        # Only the admin can edit the configuration
        if (api.bui.acl and not
                api.bui.acl.is_admin(current_user.get_id())):
            abort(403, message='Sorry, you don\'t have rights to access the setting panel')

        try:
            conf = unquote(conf)
        except:
            pass
        r = api.bui.cli.read_conf_cli(client, conf, server)
        return jsonify(results=r,
                       boolean=api.bui.cli.get_parser_attr('boolean_cli', server),
                       string=api.bui.cli.get_parser_attr('string_cli', server),
                       integer=api.bui.cli.get_parser_attr('integer_cli', server),
                       multi=api.bui.cli.get_parser_attr('multi_cli', server),
                       server_doc=api.bui.cli.get_parser_attr('doc', server),
                       suggest=api.bui.cli.get_parser_attr('values', server),
                       placeholders=api.bui.cli.get_parser_attr('placeholders', server),
                       defaults=api.bui.cli.get_parser_attr('defaults', server))


@api.resource('/api/settings/new-client',
              '/api/<server>/settings/new-client',
              endpoint='api.new_client')
class NewClient(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('newclient', type=str)

    @login_required
    def put(self, server=None):
        # Only the admin can edit the configuration
        if (api.bui.acl and not
                api.bui.acl.is_admin(current_user.get_id())):
            return {'notif': [[2, 'Sorry, you don\'t have rights to access the setting panel']]}, 403

        newclient = self.parser.parse_args()['newclient']
        if not newclient:
            return {'notif': [[2, 'No client name provided']]}, 400
        # clientconfdir = api.bui.cli.get_parser_attr('clientconfdir', server)
        # if not clientconfdir:
        #    flash('Could not proceed, no \'clientconfdir\' find', 'warning')
        #    return redirect(request.referrer)
        noti = api.bui.cli.store_conf_cli(ImmutableMultiDict(), newclient, None, server)
        if server:
            noti.append([3, '<a href="{}">Click here</a> to edit \'{}\' configuration'.format(url_for('view.cli_settings', server=server, client=newclient), newclient)])
        else:
            noti.append([3, '<a href="{}">Click here</a> to edit \'{}\' configuration'.format(url_for('view.cli_settings', client=newclient), newclient)])
        return {'notif': noti}, 201


@api.resource('/api/settings/path-expander',
              '/api/<server>/settings/path-expander',
              '/api/settings/path-expander/<client>',
              '/api/<server>/settings/path-expander/<client>',
              endpoint='api.path_expander')
class PathExpander(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('path')

    @login_required
    def get(self, server=None, client=None):
        # Only the admin can edit the configuration
        if (api.bui.acl and not
                api.bui.acl.is_admin(current_user.get_id())):
            noti = [[2, 'Sorry, you don\'t have rights to access the setting panel']]
            return {'notif': noti}, 403

        path = self.parser.parse_args()['path']
        paths = api.bui.cli.expand_path(path, client, server)
        if not paths:
            noti = [[2, "Path not found"]]
            return {'notif': noti}, 500
        return {'result': paths}


@api.resource('/api/settings/delete-client',
              '/api/<server>/settings/delete-client',
              '/api/settings/delete-client/<client>',
              '/api/<server>/settings/delete-client/<client>',
              endpoint='api.delete_client')
class DeleteClient(Resource):

    @login_required
    def delete(self, server=None, client=None):
        # Only the admin can edit the configuration
        if (api.bui.acl and not
                api.bui.acl.is_admin(current_user.get_id())):
            noti = [[2, 'Sorry, you don\'t have rights to access the setting panel']]
            return {'notif': noti}, 403

        return {'notif': api.bui.cli.delete_client(client, server)}, 200
