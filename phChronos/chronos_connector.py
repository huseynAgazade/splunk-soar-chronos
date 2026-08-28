#!/usr/bin/python
# -*- coding: utf-8 -*-
# -----------------------------------------
# Chronos - run SOAR playbooks on a schedule
# -----------------------------------------

import phantom.app as phantom
from phantom.action_result import ActionResult
from phantom.base_connector import BaseConnector

import requests
import json
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()


class RetVal(tuple):

    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class ChronosConnector(BaseConnector):

    def __init__(self):
        super(ChronosConnector, self).__init__()

        self._state = None
        self._base_url = None
        self._auth_token = None
        self._verify = False
        self._container_id = None
        self._playbook_list = None
        self._run_scope = 'new'

    # ------------------------------------------------------------------
    # response handling
    # ------------------------------------------------------------------

    def _process_empty_response(self, response, action_result):
        if response.status_code in (200, 204):
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(
            action_result.set_status(
                phantom.APP_ERROR, "Empty response and no information in the header"
            ), None
        )

    def _process_html_response(self, response, action_result):
        status_code = response.status_code

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            error_text = soup.text
            split_lines = [x.strip() for x in error_text.split('\n') if x.strip()]
            error_text = '\n'.join(split_lines)
        except Exception:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(status_code, error_text)
        message = message.replace('{', '{{').replace('}', '}}')

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR, "Unable to parse JSON response. Error: {0}".format(str(e))
                ), None
            )

        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        message = "Error from server. Status Code: {0} Data from server: {1}".format(
            r.status_code, r.text.replace('{', '{{').replace('}', '}}')
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):
        if hasattr(action_result, 'add_debug_data'):
            action_result.add_debug_data({'r_status_code': r.status_code})
            action_result.add_debug_data({'r_text': r.text})
            action_result.add_debug_data({'r_headers': r.headers})

        if 'json' in r.headers.get('Content-Type', ''):
            return self._process_json_response(r, action_result)

        if 'html' in r.headers.get('Content-Type', ''):
            return self._process_html_response(r, action_result)

        if not r.text:
            return self._process_empty_response(r, action_result)

        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
            r.status_code, r.text.replace('{', '{{').replace('}', '}}')
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _make_rest_call(self, endpoint, action_result, method="get", **kwargs):
        resp_json = None

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(
                action_result.set_status(phantom.APP_ERROR, "Invalid method: {0}".format(method)),
                resp_json
            )

        headers = kwargs.pop('headers', None) or {}
        headers['ph-auth-token'] = self._auth_token

        try:
            r = request_func(
                self._base_url + endpoint,
                verify=self._verify,
                headers=headers,
                timeout=30,
                **kwargs
            )
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR, "Error connecting to server. Details: {0}".format(str(e))
                ), resp_json
            )

        return self._process_response(r, action_result)

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _handle_test_connectivity(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Reaching {0}".format(self._base_url))
        ret_val, _ = self._make_rest_call('/rest/version', action_result)
        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Checking container {0}".format(self._container_id))
        ret_val, _ = self._make_rest_call(
            '/rest/container/{0}'.format(self._container_id), action_result
        )
        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Checking custom list '{0}'".format(self._playbook_list))
        ret_val, resp = self._make_rest_call(
            '/rest/decided_list/{0}'.format(self._playbook_list), action_result
        )
        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Found {0} row(s)".format(len(resp.get('content', []))))
        self.save_progress("Test Connectivity Passed")

        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_on_poll(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))

        ret_val, resp = self._make_rest_call(
            '/rest/decided_list/{0}'.format(self._playbook_list), action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        started = 0
        failed = 0

        for row in resp.get('content', []):
            if not row:
                continue

            entry = str(row[0]).strip()
            if not entry or entry.startswith('#'):
                continue

            body = {
                'container_id': self._container_id,
                'playbook_id': int(entry) if entry.isdigit() else entry,
                'scope': self._run_scope,
                'run': True,
            }

            ret_val, run = self._make_rest_call(
                '/rest/playbook_run', action_result, method='post', json=body
            )

            if phantom.is_fail(ret_val) or not run or not run.get('playbook_run_id'):
                self.save_progress("Could not start '{0}'".format(entry))
                failed += 1
                continue

            self.save_progress("Started '{0}' as run {1}".format(entry, run['playbook_run_id']))
            started += 1

        action_result.update_summary({'playbooks_started': started, 'playbooks_failed': failed})

        if failed:
            return action_result.set_status(
                phantom.APP_ERROR, "Started {0}, failed {1}".format(started, failed)
            )

        return action_result.set_status(
            phantom.APP_SUCCESS, "Started {0} playbook(s)".format(started)
        )

    def handle_action(self, param):
        action_id = self.get_action_identifier()
        self.debug_print("action_id", action_id)

        if action_id == 'test_connectivity':
            return self._handle_test_connectivity(param)

        if action_id == 'on_poll':
            return self._handle_on_poll(param)

        return phantom.APP_SUCCESS

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bool(value):
        if isinstance(value, str):
            return value.strip().lower() in ('true', 'yes', 'on', '1')
        return bool(value)

    def initialize(self):
        self._state = self.load_state()

        config = self.get_config()
        self._base_url = config['base_url'].rstrip('/')
        self._auth_token = config['auth_token']
        self._verify = self._to_bool(config.get('verify_server_cert', False))
        self._container_id = int(config['container_id'])
        self._playbook_list = config['playbook_list']
        self._run_scope = config.get('run_scope', 'new')

        return phantom.APP_SUCCESS

    def finalize(self):
        self.save_state(self._state)
        return phantom.APP_SUCCESS


def main():
    import argparse

    argparser = argparse.ArgumentParser()
    argparser.add_argument('input_test_json', help='Input Test JSON file')
    args = argparser.parse_args()

    with open(args.input_test_json) as f:
        in_json = json.loads(f.read())
        print(json.dumps(in_json, indent=4))

        connector = ChronosConnector()
        connector.print_progress_message = True

        ret_val = connector._handle_action(json.dumps(in_json))
        print(json.dumps(json.loads(ret_val), indent=4))

    exit(0)


if __name__ == '__main__':
    main()
