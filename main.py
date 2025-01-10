import serial
import serial.tools.list_ports
import time
import config
from enum import Enum
from typing import Optional, List, Dict

class Command:
    def __init__(self, command_dict: Dict):
        self.command = command_dict['command']
        self.wait_for = command_dict.get('wait_for')
        self.validators = command_dict.get('validators', [])
        self.error_validators = command_dict.get('error_validators', [])

    def validate_response(self, response: str) -> bool:
        # Check for error conditions first
        for error in self.error_validators:
            if error in response:
                raise Exception(f"Error in command execution: {error}")

        # If no validators specified, any response is valid
        if not self.validators:
            return True

        # Check if any validator matches
        return any(validator in response for validator in self.validators)

class CommandFactory:
    @staticmethod
    def create_rsa_key_command() -> Command:
        return Command(
            command="crypto key generate rsa",
            wait_for="RSA Key pair is successfully created",
            validators=[
                "Creating RSA key pair, please wait",
                "Key already exists"
            ]
        )

    @staticmethod
    def create_ssl_cert_command() -> Command:
        return Command(
            command="crypto-ssl certificate generate",
            wait_for="ssl-certificate creation is successful",
            validators=["Creating certificate, please wait"]
        )

    @staticmethod
    def create_simple_command(command: str) -> Command:
        return Command(command=command)

class AccessLevel(Enum):
    LOGGED_OUT = 0
    USER = 1
    PRIVILEGED = 2
    CONFIG = 3

class Connection:
    def __init__(self, port):
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1
        )

        self.wait_fors = []

        # Send newline to get a prompt and check current access level
        response = self.send_command('')
        self.access_level = self.check_access_level(response)

        if self.access_level is AccessLevel.LOGGED_OUT:
            response = self.login(response=response)
            self.access_level = self.check_access_level(response)

        assert self.access_level is not AccessLevel.LOGGED_OUT

    def get_response(self):
        response = self.ser.read_all().decode()
        for wait_for in self.wait_fors:
            if wait_for in response:
                self.wait_fors.remove(wait_for)
                return response
        return response

    def send_command(self, command: str, sleep=1):
        self.ser.write((command + '\n').encode())
        time.sleep(sleep)
        response = self.get_response()
        return response

    def check_access_level(self, response: str):
        if response.endswith('(config)#'):
            return AccessLevel.CONFIG
        elif response.endswith('#'):
            return AccessLevel.PRIVILEGED
        if response.endswith('>'):
            return AccessLevel.USER
        else:
            return AccessLevel.LOGGED_OUT
        
    def login(self, response:str=''):
        # We may need to cycle through a few prompts to get to the username prompt
        for _ in range(5):
            if 'Please Enter Login Name:' in response:
                break
            response = self.send_command('')
        else:
            raise Exception('Could not find login prompt')

        response = self.send_command(config.username)
        assert 'Please Enter Password:' in response
        response = self.send_command(config.password)
        assert 'User login successful' in response

        return response

    def execute_command(self, command: Command) -> str:
        response = self.send_command(command.command)

        if not command.validate_response(response):
            raise Exception(f"Command '{command.command}' failed validation.\nResponse: {response}")
        
        if command.wait_for:
            self.wait_fors.append(command.wait_for)

        return response
    
    def close(self):
        self.ser.close()

def get_serial_port():
    ports = serial.tools.list_ports.comports()
    if not ports:
        raise Exception('No COM ports found')
    
    if len(ports) == 1:
        port = ports[0].device
    else:
        print('Multiple COM ports found:')
        print('\n'.join([('  ' + port.device) for port in ports]))
        port = input("Enter the desired COM port: ")

    return port

def main():
    port = get_serial_port()
    print(f'Using COM port: {port}')
    
    conn = Connection(port)
    
    # Execute all commands from config
    for cmd_dict in config.commands:
        command = Command(cmd_dict)
        try:
            response = conn.execute_command(command)
            print(f"Command: {command.command}\nResponse: {response}\n")
        except Exception as e:
            print(f"Error executing command '{command.command}': {str(e)}")
            break

    while conn.wait_fors:
        print("Waiting for async command completion...")
        time.sleep(1)
        response = conn.get_response()
        if response:
            print(f"Response: {response}")

    write_mem = Command(command="write memory", validators=["Configuration saved to NVRAM"])
    to_user_mode = Command(command="exit", validators=[">"])
    to_logout = Command(command="exit", validators=["Press Enter key to login"])

    conn.execute_command(write_mem)
    conn.execute_command(to_user_mode)
    conn.execute_command(to_logout)

    conn.close()

if __name__ == "__main__":
    main()