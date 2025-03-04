#!/usr/bin/env python3

# by TheTechromancer

import os
import sys
import logging
import argparse
import requests
from shutil import which
from pathlib import Path
from getpass import getpass

from urllib3.exceptions import InsecureRequestWarning

# Suppress only the single warning from urllib3 needed.
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

package_path = Path(__file__).resolve().parent
sys.path.append(str(package_path))

from lib import logger
import lib.util as util
from lib.sprayer import TrevorSpray
from lib.errors import TREVORSprayError

log = logging.getLogger('trevorspray.cli')


def main():

    module_dir = Path(__file__).parent / 'lib/sprayers'
    module_files = list(os.listdir(module_dir))
    module_choices = []
    for file in module_files:
        file = module_dir / file
        if file.is_file() and file.suffix.lower() == '.py' and not file.stem == 'base':
            module_choices.append(file.stem)

    parser = argparse.ArgumentParser(description='A password sprayer with the option to load-balance traffic through SSH hosts')

    parser.add_argument('-u', '--users', nargs='+', default=[], help='Usernames(s) and/or file(s) containing usernames')
    parser.add_argument('-p', '--passwords', nargs='+', default=[], help='Password(s) that will be used to perform the password spray')
    parser.add_argument('--url', help='The URL to spray against')
    parser.add_argument('-t', '--threads', type=int, default=1, help='Max number of concurrent requests (default: 1)')
    parser.add_argument('-r', '--recon', metavar='DOMAIN', nargs='+', help='Retrieves MX records and info related to authentication, email, Azure, Microsoft 365, etc.')
    parser.add_argument('-f', '--force', action='store_true', help='Forces the spray to continue and not stop when multiple account lockouts are detected')
    parser.add_argument('-d', '--delay', type=float, default=0, help='Sleep for this many seconds between requests')
    parser.add_argument('-ld', '--lockout-delay', type=float, default=0, help='Sleep for this many additional seconds when a lockout is encountered')
    parser.add_argument('-j', '--jitter', type=float, default=0, help='Add a random delay of up to this many seconds between requests')
    parser.add_argument('-e', '--exit-on-success', action='store_true', help='Stop spray when a valid cred is found')
    parser.add_argument('-nl', '--no-loot', action='store_true', help='Don\'t execute loot activites for valid accounts')
    parser.add_argument('--timeout', type=float, default=10, help='Connection timeout in seconds (default: 10)')
    parser.add_argument('--random-useragent', action='store_true', help='Add a random value to the User-Agent for each request')
    parser.add_argument('-m', '--module', choices=module_choices, default='msol', help='Spray module to use (default: msol)')
    parser.add_argument('-6', '--prefer-ipv6', action='store_true', help='Prefer IPv6 over IPv4')
    parser.add_argument('--proxy', help='Proxy to use for HTTP and HTTPS requests')
    parser.add_argument('-v', '--verbose', '--debug', action='store_true', help='Show which proxy is being used for each request')

    ssh_parser = parser.add_argument_group(title='SSH Proxy', description='Round-robin traffic through remote systems via SSH (overrides --threads)')
    ssh_parser.add_argument('-s', '--ssh', default=[], metavar='USER@SERVER', nargs='+', help='Round-robin load-balance through these SSH hosts (user@host) NOTE: Current IP address is also used once per round')
    ssh_parser.add_argument('-i', '-k', '--key', help='Use this SSH key when connecting to proxy hosts')
    ssh_parser.add_argument('-kp', '--key-pass', action='store_true', help=argparse.SUPPRESS)
    ssh_parser.add_argument('-b', '--base-port', default=33482, type=int, help='Base listening port to use for SOCKS proxies')
    ssh_parser.add_argument('-n', '--no-current-ip', action='store_true', help='Don\'t spray from the current IP, only use SSH proxies')

    subnet_parser = parser.add_argument_group(title='Subnet Proxy', description='Send traffic from random addresses within IP subnet')
    subnet_parser.add_argument('--interface', help='Interface to send packets on')
    subnet_parser.add_argument('--subnet', help='Subnet to send packets from')

    try:

        options = parser.parse_args()

        conflicting_options = [options.subnet, options.ssh, options.proxy]
        if conflicting_options.count(None) + conflicting_options.count([]) < 2:
            log.error('Cannot specify --ssh, --subnet, or --proxy together')
            sys.exit(1)

        if options.proxy and options.ssh:
            log.error('Cannot specify --proxy with --ssh because the SSH hosts are already used as proxies')
            sys.exit(1)

        # Monkey patch to prioritize IPv4 or IPv6
        import socket
        old_getaddrinfo = socket.getaddrinfo
        if options.prefer_ipv6:
            def new_getaddrinfo(*args, **kwargs):
                addrs = old_getaddrinfo(*args, **kwargs)
                addrs.sort(key=lambda x: x[0], reverse=True)
                return addrs
        else:
            def new_getaddrinfo(*args, **kwargs):
                addrs = old_getaddrinfo(*args, **kwargs)
                addrs.sort(key=lambda x: x[0])
                return addrs
        socket.getaddrinfo = new_getaddrinfo

        if options.proxy:
            os.environ['HTTP_PROXY'] = options.proxy
            os.environ['HTTPS_PROXY'] = options.proxy

        if options.verbose:
            trevorproxy_logger = logging.getLogger('trevorproxy')
            trevorproxy_logger.setLevel(logging.DEBUG)
            trevorspray_logger = logging.getLogger('trevorspray')
            trevorspray_logger.setLevel(logging.DEBUG)
            trevorproxy_logger.handlers = trevorspray_logger.handlers

        if not (options.users and options.passwords):
            if not options.recon:
                log.error('Please specify --users and --passwords, or --recon')
                sys.exit(2)
        else:
            options.users = list(util.files_to_list(options.users).keys())

        if options.no_current_ip and not options.ssh:
            log.error('Cannot specify --no-current-ip without giving --ssh hosts')
            sys.exit(1)

        if options.ssh and util.ssh_key_encrypted(options.key):
            options.key_pass = getpass('SSH key password (press enter if none): ')

        if options.subnet:
            # make sure executables exist
            for binary in ['iptables']:
                if not which(binary):
                    log.error(f'Please install {binary}')
                    sys.exit(1)

        log.info(f'Command: {" ".join(sys.argv)}')
        sprayer = TrevorSpray(options)
        sprayer.go()

    except argparse.ArgumentError as e:
        log.error(e)
        log.error('Check your syntax')
        sys.exit(2)

    except TREVORSprayError as e:
        log.error(str(e))

    except Exception as e:
        if options.verbose:
            import traceback
            log.error(traceback.format_exc())
        else:
            log.error(f'Encountered error (-v to debug): {e}')

    except KeyboardInterrupt:
        log.error('Interrupted')
        sys.exit(1)

if __name__ == '__main__':
    main()