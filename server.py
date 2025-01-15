import socket
import threading
import time
import struct
import random
from config import *
from colorama import init, Fore , Back

# Initialize the library for colored output in the terminal
init(autoreset=True)


def allocate_port(start, end, protocol):
    """
    Find an available port for a specified protocol.
    This function will check for an available port in the specified range 
    and return the first available one.
    """
    # Select socket type based on protocol (TCP or UDP)
    proto = socket.SOCK_STREAM if protocol == 'tcp' else socket.SOCK_DGRAM   #creating a socket

    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, proto) as sock:
            try:
                # Try binding to the port, if it works, the port is available
                sock.bind(('0.0.0.0', port))
                return port   #Return port number
            except OSError:
                continue   #If the port is not available try another
    
    # If no available port is found, raise an exception        
    raise RuntimeError("No available port found.")




def offer_broadcast(udp_port, tcp_port):
    """
    Broadcasts offers to all clients on the network over UDP.
    This function sends out an 'offer' message containing the UDP and TCP ports 
    that the server is using. The offer is sent every second.
    """
    # Pack the offer packet with the server's UDP and TCP port
    offer_packet = struct.pack('!IBHH', MAGIC_COOKIE, MTYPE_OFFER, udp_port, tcp_port)

    # Create a UDP socket to send the broadcast message
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as broadcast_offer_socket:
        broadcast_offer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Enable broadcasting
        while True:
            # Send the offer packet to all clients on the network
            broadcast_offer_socket.sendto(offer_packet, ('172.18.255.255', BROADCAST_PORT))  # Broadcasting on port 13117
            time.sleep(1)  # Sleep for 1 second before broadcasting again




def process_tcp_connection(connection, client_address):
    """
    Process file transfer requests over a TCP connection.

    Workflow:
    1. Receive the requested file size from the client.
    2. Send the requested amount of data back to the client.
    3. Close the connection after sending the data.
    """
    try:
        # Receive the file size from the client
        received_data = connection.recv(CONST_SIZE).decode().strip()  # Read a fixed size of bytes and decode
        total_file_size = int(received_data)  # Convert the received size to an integer

        bytes_transferred = 0  # Tracks the total number of bytes sent
        chunk_size = CONST_SIZE * 8  # Defines the size of each data chunk (8KB)

        # Loop to send the file in chunks
        while bytes_transferred < total_file_size:
            remaining_bytes = total_file_size - bytes_transferred  # Calculate remaining bytes to send
            current_chunk_size = min(chunk_size, remaining_bytes)  # Determine the size of the next chunk
            chunk_data = bytearray(random.getrandbits(8) for _ in range(current_chunk_size))  # Generate random data

            try:
                connection.sendall(chunk_data)  # Send the data chunk
            except Exception as e:
                print(Fore.WHITE + Back.RED + f"Error: Connection with {client_address} lost unexpectedly.")  # Log connection issue
                break  # Exit the loop if an error occurs

            bytes_transferred += current_chunk_size  # Update the transferred bytes counter

    except ValueError:
        print(Fore.WHITE + Back.RED + f"Invalid file size received from {client_address}.")  # Log invalid file size error
    finally:
        connection.close()  # Ensure the connection is closed after processing




def process_udp_connection(packet_data, client_address):
    """
    Processes incoming UDP packets and responds with segmented payloads.
    The client sends a request specifying the size of the data they want to receive, 
    and the server sends the requested data in chunks.

    Parameters:
    - packet_data: The raw data received from the client (bytes).
    - client_address: A tuple containing the client's IP address and port.

    This function validates the incoming request, splits the data into segments, 
    and sends them back to the client over UDP in bursts.
    """
    try:
        # Extract values from the incoming packet using the expected structure
        cookie, message_type, file_size_bytes = struct.unpack('!IBQ', packet_data)

        # Validate the values
        if cookie != MAGIC_COOKIE or message_type != MTYPE_REQUEST:
            print(Fore.WHITE + Back.RED + "Received invalid magic cookie or message type. Ignoring packet.")
            return

        # Calculate how many segments are needed based on the requested data size
        num_segments = (file_size_bytes + CONST_SIZE - 1) // CONST_SIZE   # Round up for partial chunks

        # Initialize a new UDP socket for sending the response
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, CONST_SIZE)

        try:
            # Generate the segments
            segments_list = []
            for segment_index in range(num_segments):
                remaining_bytes = file_size_bytes - (segment_index * CONST_SIZE)
                current_chunk_size = min(CONST_SIZE, remaining_bytes)

                # Generate random payload data
                payload_data = bytearray(random.getrandbits(8) for _ in range(current_chunk_size))

                # Create the payload header
                payload_header = struct.pack('!IBQQ', MAGIC_COOKIE, MTYPE_PAYLOAD, num_segments, segment_index)

                # Add the full segment (header + payload) to the list
                segments_list.append(payload_header + payload_data)

            # Send the segments in bursts to avoid network congestion
            burst_limit = 32
            for start_index in range(0, num_segments, burst_limit):
                for segment_index in range(start_index, min(start_index + burst_limit, num_segments)):
                    udp_socket.sendto(segments_list[segment_index], client_address)
                time.sleep(0.001)  # Add a short delay between bursts to reduce congestion

        finally:
            udp_socket.close()

    except struct.error:
        # Handle errors if the incoming packet doesn't match the expected format
        print(Fore.WHITE + Back.RED + "Failed to unpack the packet. Invalid format.")

    except Exception as error:
        # Handle any unexpected errors during the process
        print(Fore.WHITE + Back.RED + f"An unexpected error occurred while processing the UDP packet: {error}")




def run_server():
    """
    Start running the server, broadcasts offers, and listens for incoming TCP and UDP connections.
    """
    server_ip = socket.gethostbyname(socket.gethostname())
    print(Fore.CYAN + Back.MAGENTA + f"Team {TEAM_NAME} Server started, listening on IP address {server_ip}")
    
    # allocate port for TCP and UDP to be used in the offer broadcast thread 
    udp_port = allocate_port(1025, 65535, 'udp')
    tcp_port = allocate_port(1025, 65535, 'tcp')
    
    # Start the broadcast thread
    threading.Thread(target=offer_broadcast, args=(udp_port, tcp_port), daemon=True).start()

    # Setting up the TCP listener socket
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind(('', tcp_port))   # Binding the socket to the selected TCP port
    tcp_socket.listen(10)  # Set maximum pending connections to 10

    # Setting up the UDP listener socket
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(('', udp_port))   # Binding the socket to the selected UDP port

    while True:
        try:
            tcp_socket.setblocking(False)  # Non-blocking mode
            # Handle TCP client connection
            try:
                conn, addr = tcp_socket.accept()
                thread = threading.Thread(target=process_tcp_connection, args=(conn, addr), daemon=True)
                thread.start()
            except BlockingIOError:
                pass  # No incoming TCP connections

            udp_socket.setblocking(False)  # Non-blocking mode
            # Handle UDP packets
            try:
                data, addr = udp_socket.recvfrom(CONST_SIZE)
                threading.Thread(target=process_udp_connection, args=(data, addr), daemon=True).start()
            except BlockingIOError:
                pass  # No incoming UDP packets

        except Exception as e:
            print(Fore.WHITE + Back.RED + f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    run_server()

