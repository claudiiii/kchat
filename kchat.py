#!/usr/bin/env python

import logging
import asyncio
import click
import random
import sys
import json
import uuid
import queue

from kademlia.network import Server


def setup_logging():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    log = logging.getLogger("kademlia")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)


def got_stdin_data(q):
    """
    Helper to get the input on stdin and writs it to a queue.
    """
    asyncio.create_task(q.put(sys.stdin.readline()))


@click.command()
@click.option("-i", "--ip", type=str, help="Ip address of the bootstrap node.")
@click.option("-p", "--port", type=int, help="Port of the bootstrap node.")
@click.option("-n", "--name", type=str, help="Name of the node.")
@click.option("--debug/--no-debug", default=False, help="Enable debug logging.")
def entrypoint(ip, port, name, debug):
    if debug:
        setup_logging()
    loop = asyncio.get_event_loop()
    if debug:
        loop.set_debug(True)
    input_queue = asyncio.Queue()
    loop.add_reader(sys.stdin, got_stdin_data, input_queue)
    loop.run_until_complete(main(ip, port, name, input_queue))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # server.stop()
        loop.close()


async def sync(members, server, name, last_message_id):
    """
    Synchronize peers, announces their name and last message.
    Also gets the names and last messages for all other peers
    who announced them.
    """
    log = logging.getLogger("kademlia")
    members_raw = await server.get("SYNC")
    if members_raw is not None:
        members = json.loads(members_raw)
        log.info(members)

    members[str(server.node.id)] = {"name": name, "last_message": last_message_id}
    await server.set("SYNC", json.dumps(members))

    return members


async def main(ip, port, name, input_queue):
    server = Server()
    listen_port = random.randrange(8400, 8500)
    await server.listen(listen_port)
    print(f"Listening on port: {listen_port}")
    # Bootstrap from node when ip and port are provided
    if ip is not None and port is not None:
        bootstrap_node = (ip, port)
        await server.bootstrap([bootstrap_node])

    members = {}
    known_messages = {}
    last_message_id = None

    while True:
        members = await sync(members, server, name, last_message_id)
        for member in members.keys():
            # Skip this peer, prevents printing messages from us
            if member == str(server.node.id):
                continue

            messages = queue.Queue()
            last = members[member]["last_message"]
            # Skip when no last message, prevent breaking when running a single node
            if last is None:
                continue

            member_message = json.loads(await server.get(last))

            # New peer in the sync table
            if not member in known_messages:
                messages.put("--> {} joined".format(members[member]["name"]))
                messages.put(member_message["text"])
                known_messages[member] = last

            elif not known_messages[member] == last:
                messages.put(member_message["text"])
                # As long as there are previous messages that are newer than the last one
                # we know about add them to the message queue
                while not member_message["prev"] == known_messages[member]:
                    message = await server.get(member_message["prev"])
                    if not message is None:
                        member_message = json.loads(message)
                        messages.put(member_message["text"])
                    else:
                        break
                known_messages[member] = last

            while not messages.empty():
                print("{}: ".format(members[member]["name"]), messages.get())

        # When we get input on stdin
        if not input_queue.empty():
            input_data = input_queue.get_nowait()
            text = input_data.strip()
            message = {"prev": last_message_id, "text": text}
            message_id = str(uuid.uuid1())
            await server.set(message_id, json.dumps(message))
            last_message_id = message_id

        await asyncio.sleep(1)


if __name__ == "__main__":
    entrypoint()
