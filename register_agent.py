#!/usr/bin/env python3

import json
import os
import sys
from subprocess import PIPE, Popen  # nosec

import psutil
import urllib3
from base64 import b64encode
from healthcheck import HealthCheck
from jinja2 import Template,Environment, FileSystemLoader
from loguru import logger
from http.server import BaseHTTPRequestHandler, HTTPServer
import time

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    import requests
except ModuleNotFoundError as e:
    logger.error("No module 'requests' found. Install: pip install requests")
    sys.exit(1)

health = HealthCheck()


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        raise NotImplementedError("notImplemented() cannot be performed because ...")

    def sent_request(self):
        message, status_code, headers = health.run()
        try:
            request_path = str(self.path).reprunlace("\n", " ")
            response_msg = http_codes_serializer(
                response=json.loads(message), status_code=status_code
            )
            logger.info(
                f"GET request. path: {request_path} headers: {headers}, response: {response_msg}"
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(bytes(message, encoding="utf8"))
        except TypeError:
            self.send_response(500)


def json_serialize(record):
    subset = {"timestamp": record["time"].timestamp(), "message": record["message"]}
    return json.dumps(subset)


def get_serialize(message):
    serialized = json_serialize(message.record)
    print(serialized)


def http_codes_serializer(response, status_code):
    msg = json.dumps(response, indent=4, sort_keys=True)
    code = f"status: {status_code} - {code_desc(status_code)}"
    return f"{json.loads(msg)} {code}"


def create_config_file(CustomConfigPath):
    env = Environment(loader=FileSystemLoader(os.getcwd()))
    logger.info(f"Create Wazuh agent configuration for node {node_name}")
    if CustomConfigPath == "":
        logger.info("Using default config file ossec.jinja2")
        template = env.get_template("ossec.jinja2")   
        config = template.render(
            join_manager_hostname=join_manager_worker,
            join_manager_port=join_manager_port,
            virus_total_key=virus_total_key,
        )
        wazuh_config_file = open("/var/ossec/etc/ossec.conf", "w")
        wazuh_config_file.write(f"{config} \n")
        logger.info(f"Config file has been written to /var/ossec/etc/ossec.conf")
        wazuh_config_file.close()
    else:
        logger.info(f"Using custom config file {CustomConfigPath}")
        logger.info("current working directory is: " + os.getcwd())
        # with open("custom-ossec.jinja2") as file_:
        #     template = Template(file_.read(), autoescape=True)
        #     config = template.render(
        #         join_manager_hostname=join_manager_worker,
        #         join_manager_port=join_manager_port,
        #         virus_total_key=virus_total_key,
        #         CustomConfigPath=CustomConfigPath,
        #     )
        #     wazuh_config_file = open("/var/ossec/etc/ossec.conf", "w")
        #     wazuh_config_file.write(f"{config} \n")
        #     logger.info(f"Config file has been written to /var/ossec/etc/ossec.conf")
        #     wazuh_config_file.close()
        template = env.get_template("custom-ossec.jinja2")
        config = template.render(
            join_manager_hostname=join_manager_worker,
            join_manager_port=join_manager_port,
            virus_total_key=virus_total_key,
            CustomConfigPath=CustomConfigPath,
        )
        wazuh_config_file = open("/var/ossec/etc/ossec.conf", "w")
        wazuh_config_file.write(f"{config} \n")
        logger.info(f"Config file has been written to /var/ossec/etc/ossec.conf")
        wazuh_config_file.close()
        
    open("/var/ossec/etc/local_internal_options.conf", "wb").write(
        open("local_internal_options.jinja2", "rb").read()
    )
    logger.info(
        "Configuraconftion has been generated from template, starting Wazuh agent provisioning"
    )


def delete_agent(agt_name):
    status_code, response = wazuh_api("get", f"agents?pretty=true&q=name={agt_name}")
    print(response, status_code)
    for items in response["data"]["affected_items"]:
        print(f"Item {items}")
        status_code, response = wazuh_api(
            "delete",
            f"agents?pretty=true&older_than=0s&agents_list={items['id']}&status=all",
        )
        msg = json.dumps(response, indent=4, sort_keys=True)
        code = f"Status: {status_code} - {code_desc(status_code)}"
        logger.error(f"INFO - DELETE AGENT:\n{code}\n{msg}")
    status_code, response = wazuh_api(
        "delete",
        "agents?pretty=true&older_than=21d&agents_list=all&status=never_connected,disconnected",
    )
    for items in response["data"]["affected_items"]:
        status_code, response = wazuh_api(
            "delete",
            f"agents?pretty=true&older_than=0s&agents_list={items['id']}&status=all",
        )
        msg = json.dumps(response, indent=4, sort_keys=True)
        code = f"Status: {status_code} - {code_desc(status_code)}"
        logger.error(f"INFO - DELETE AGENT:\n{code}\n{msg}")


def wazuh_api(method, resource, data=None):
    code = None
    response_json = {}
    session = requests.Session()
    retry = Retry(connect=int(max_retry_count), backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    login_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {b64encode(auth).decode()}",
    }
    response = session.get(login_url, headers=login_headers, verify=False)  # nosec
    logger.info(
        f"Response code {response.status_code} response content {response.content}"
    )
    token = json.loads(response.content.decode())["data"]["token"]
    requests_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    url = f"{base_url}/{resource}"
    try:
        if method.lower() == "post":
            response = session.post(
                url, headers=requests_headers, data=json.dumps(data), verify=verify
            )
        elif method.lower() == "put":
            response = session.put(
                url, headers=requests_headers, data=data, verify=verify
            )
        elif method.lower() == "delete":
            response = session.delete(
                url, headers=requests_headers, data=data, verify=verify
            )
        else:
            response = session.get(
                url, headers=requests_headers, params=data, verify=verify
            )

        code = response.status_code
        response_json = response.json()

    except Exception as exception:
        logger.error(f"Error: for resource {resource}, exception {exception}")

    return code, response_json


def check_self():
    process_name = os.path.basename(__file__)
    for proc in psutil.process_iter():
        for process in process_name:
            if process in proc.name():
                return True, "register_agent ok"


health.add_check(check_self)


def code_desc(http_status_code):
    return requests.status_codes.codes[http_status_code]


def get_agent_id(agt_name):
    status_code, response = wazuh_api(
        "get", f"agents?pretty=true&q=name={agt_name}&wait_for_complete=true"
    )
    logger.debug(f"Response {status_code}: {response}")
    for agt_status in response["data"]["affected_items"]:
        try:
            agn_id = agt_status["id"]
            delete_agent(agt_name)
            logger.info(f"Found wazuh agent with id {agn_id} try to re-use")
            return agn_id
        except KeyError as err:
            logger.error(f"Got error while trying to get id {err}")
            return None


def add_agent_to_group(wazuh_agent_id, agent_group):
    status_code, response = wazuh_api(
        "put",
        f"agents/{wazuh_agent_id}/group/{agent_group}?pretty=true&wait_for_complete=true",
    )
    response_msg = http_codes_serializer(response=response, status_code=status_code)

    if status_code == 200 and response["error"] == 0:
        logger.info(
            f"Wazuh agent id {wazuh_agent_id} has been assigned to group {agent_group}. Response {response_msg}"
        )
        return response
    else:
        logger.error(f"ERROR: Unable to add agent to group {response_msg}, retry")
        add_agent_to_group(wazuh_agent_id, agent_group)


def add_agent(agt_name, agt_ip=None):
    agt_id = get_agent_id(agt_name)
    if agt_ip and agt_id:
        agt_data = {
            "name": str(agt_name),
            "ip": agt_ip,
            "id": agt_id,
        }
    elif agt_id:
        agt_data = {"name": str(agt_name), "id": agt_id}
    else:
        agt_data = {"name": str(agt_name)}
    logger.info(f"Try to add agent with data {agt_data}")
    status_code, response = wazuh_api(
        "post",
        "agents/insert",
        agt_data,
    )
    response_msg = http_codes_serializer(response=response, status_code=status_code)
    if status_code == 400:
        logger.error(f"During adding Wazuh agent request return {response_msg}")
    elif status_code == 200 and response["error"] == 0:
        wazuh_agent_id = response["data"]["id"]
        wazuh_agent_key = response["data"]["key"]
        logger.info(
            f"Wazuh agent for node '{node_name}' with ID '{wazuh_agent_id}' has been added. Response {response_msg}"
        )
        return wazuh_agent_id, wazuh_agent_key
    else:
        logger.error(f"Unable to add agent {agt_name}: {response_msg}")


def wazuh_agent_status(agt_name, pretty=None):
    if pretty:
        status_code, response = wazuh_api(
            "get", f"agents?pretty=true&q=name={agt_name}&wait_for_complete=true"
        )
    else:
        status_code, response = wazuh_api(
            "get", f"agents?q=name={agt_name}&wait_for_complete=true"
        )
    response_msg = http_codes_serializer(response=response, status_code=status_code)
    if status_code == 200 and response["error"] == 0:
        wazuh_agt_name = None
        wazuh_agt_status = None
        for items in response["data"]["affected_items"]:
            wazuh_agt_name = items["name"]
            wazuh_agt_status = items["status"]
        logger.info(f"Wazuh agent status: {response_msg}")
        return wazuh_agt_name, wazuh_agt_status
    else:
        logger.error(f"Unable to get Wazuh agent status: {response_msg}")


def wazuh_agent_import_key(wazuh_agent_key):
    cmd = "/var/ossec/bin/manage_agents"
    std_out, std_err, return_code = execute([cmd, "-i", wazuh_agent_key], "y\n\n")
    if return_code != 0:
        msg = std_err.replace("\n", " ")
        logger.error(f"Error during importing key: {msg}")
    else:
        msg = std_out.replace("\n", " ")
        logger.info(f"Key has been imported {msg}")


def execute(cmd_list, stdin=None):
    process = Popen(
        cmd_list,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        encoding="utf8",
        shell=False,  # nosec
    )
    process_out, process_err = process.communicate(stdin)
    return_code = process.returncode
    return process_out, process_err, return_code


def restart_wazuh_agent():
    cmd = "/var/ossec/bin/wazuh-control"
    command_stdout, command_stderr, _ = execute([cmd, "restart"])
    restarted = False

    for line_output in command_stdout.split(os.linesep):
        if "Completed." in line_output:
            restarted = True
            logger.info("Wazuh agent has been restarted")
            break

    if not restarted:
        logger.error(f"error during restarting Wazuh agent: {command_stderr}")


if __name__ == "__main__":
    logger.remove()
    logger.add(get_serialize)
    protocol = os.environ.get("JOIN_MANAGER_PROTOCOL", default="https")
    host = os.environ.get(
        "JOIN_MANAGER_MASTER_HOST", default="wazuh.wazuh.svc.cluster.local"
    )
    user = os.environ.get("JOIN_MANAGER_USER", default="")
    password = os.environ.get("JOIN_MANAGER_PASSWORD", default="")
    node_name = os.environ.get("NODE_NAME")
    port = os.environ.get("JOIN_MANAGER_API_PORT")
    join_manager_port = os.environ.get("JOIN_MANAGER_PORT", default=1514)
    groups = os.environ.get("WAZUH_GROUPS", default="default")
    virus_total_key = os.environ.get("VIRUS_TOTAL_KEY")
    join_manager_worker = os.environ.get(
        "JOIN_MANAGER_WORKER_HOST", default="wazuh-workers.wazuh.svc.cluster.local"
    )
    wait_time = os.environ.get("WAZUH_WAIT_TIME", default="10")
    max_retry_count = os.environ.get("MAX_RETRY_COUNT", default=10)
    if not node_name:
        node_name = os.environ.get("HOSTNAME")
    CustomConfigPath = os.environ.get("CustomConfigPath", default="")
    login_endpoint = "security/user/authenticate"
    base_url = f"{protocol}://{host}:{port}"
    login_url = f"{protocol}://{host}:{port}/{login_endpoint}"
    auth = f"{user}:{password}".encode()
    verify = False
    create_config_file(CustomConfigPath)
    agent_id, agent_key = add_agent(node_name)
    wazuh_agent_import_key(agent_key.encode())
    restart_wazuh_agent()
    status = True
    while status:
        agent_name, agent_status = wazuh_agent_status(node_name)
        if agent_status == "active":
            logger.info(
                f"Wazuh agent '{agent_name}' is ready and connected,  status - '{agent_status}......"
            )
            logger.info(
                f"Wazuh Agent {agent_name} has been connected to server {join_manager_worker}......"
            )
            status = False
        else:
            logger.info(
                f"Waiting for Wazuh agent {agent_name} become ready current status is {agent_status}......"
            )
            time.sleep(int(wait_time))
    if groups != "default":
        for group in list(groups.split(",")):
            add_agent_to_group(agent_id, group)
    logger.info("Listening on 0.0.0.0:5000")
    server = HTTPServer(("0.0.0.0", 5000), RequestHandler)
    server.serve_forever()
