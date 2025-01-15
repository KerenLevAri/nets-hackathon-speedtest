import socket
import struct
import threading
import time
from config import *
from colorama import Fore, init, Back

# Initialize the library for colored output in the terminal
init(autoreset=True)

def values_from_user():
    """
    Ask the user for the requested values
    """
    while True:
        try:
            # Ask the user to provied the requested values
            file_size = int(input("Enter requested file size (bytes): "))
            tcp_conn_num = int(input("Enter requested number of TCP connections: "))
            udp_conn_num = int(input("Enter requested number of UDP connections: "))

            # Check if the value provided are valid
            if file_size <= 0 or tcp_conn_num <= 0 or udp_conn_num <= 0:   # All values should be positive
                raise ValueError()
            return file_size, tcp_conn_num, udp_conn_num
        
        # If provided wrong values throw an error 
        except ValueError as e:
            print(Fore.WHITE + Back.RED + "Invalid input. Please enter positive values")



def find_server_offer():
    """
    Listens for broadcast offers from servers on the network and returns the first valid offer.
    
    Returns:
        Tuple: (server_ip, udp_port, tcp_port) of the server sending a valid offer.
    """
    # Create a UDP socket and configure it for reuse
    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener_socket.bind(('', BROADCAST_PORT))  # Bind to the specified port to listen for broadcasts

    while True:
        try:
            # Listen for incoming broadcast data
            offer_data, sender_address = listener_socket.recvfrom(CONST_SIZE)

            # Unpack the received data to retrieve the offer details
            try:
                magic_cookie, message_type, udp_port, tcp_port = struct.unpack('!IBHH', offer_data)
            except struct.error:   # Recieved malformed offer packet so ignores it
                print(Fore.WHITE + Back.RED + "Malformed offer packet received")
                continue

            # Validate the offer details
            if magic_cookie == MAGIC_COOKIE and message_type == MTYPE_OFFER:
                print(Fore.CYAN + Back.MAGENTA + f"Received offer from {sender_address[0]}")
                return sender_address[0], udp_port, tcp_port
            else:
                print(Fore.WHITE + Back.RED + "Received invalid offer")

        except Exception as error:
            print(Fore.WHITE + Back.RED + f"Error while waiting for offers: {str(error)}")



def manage_tcp_connection(server_ip, tcp_port, file_size, connection_number):
    """
    Establishes a TCP connection with the server, requests a file of the specified size,
    and calculates the time and speed of the transfer.

    Args:
        server_ip (str): The IP address of the server.
        tcp_port (int): The TCP port on which to connect.
        file_size (int): Size of the file to request (in bytes).
        connection_number (int): Identifier for the current connection.
    """
    try:
        # Create a TCP socket and establish a connection with the server
        client_tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_tcp_socket.connect((server_ip, tcp_port))

        # Send the requested file size to the server
        client_tcp_socket.sendall(f"{file_size}\n".encode())

        # Start measuring the transfer time
        start_time = time.time()

        # Initialize variables for tracking received data
        bytes_received = 0
        chunk_size = CONST_SIZE * 8  # Maximum size of a single data chunk

        # Continuously receive data until the requested file size is reached
        while bytes_received < file_size:
            data_to_rcv = client_tcp_socket.recv(min(chunk_size, file_size - bytes_received))
            if not data_to_rcv:
                break
            bytes_received += len(data_to_rcv)

        # Calculate and print transfer statistics
        total_time = time.time() - start_time
        transfer_speed_bps = (bytes_received / total_time) * 8  # Convert to bits per second

        # Print the resault values as asked
        print(Fore.WHITE + Back.GREEN + f"TCP transfer #{connection_number} completed:\n"
                          f"  Total time: {total_time:.2f} seconds\n"
                          f"  Average speed: {transfer_speed_bps:.1f} bits/second")

    except Exception as error:
        print(Fore.WHITE + Back.RED + f"Error in TCP connection #{connection_number}: {str(error)}")
    
    finally:
        # Ensure the socket is closed properly
        client_tcp_socket.close()



def manage_udp_connection(server_ip, udp_port, file_size, connection_number):
    """
    Handles the UDP transfer process with the server.
    It sends a request to the server for the specified file size and handles incoming data.

    Args:
        server_ip (str): The IP address of the server.
        udp_port (int): The UDP port number to connect to.
        file_size (int): The size of the file to request from the server.
        conn_num (int): The connection number for this transfer.
    """

    try:
        # Create a UDP socket with a timeout for receiving data
        client_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_udp_socket.settimeout(0.3)   # Set timeout to avoid waiting indefinitely

        # Send the request to the server with the magic cookie, message type, and file size
        request_data = struct.pack('!IBQ', MAGIC_COOKIE, MTYPE_REQUEST, file_size)
        client_udp_socket.sendto(request_data, (server_ip, udp_port))

        start_time = time.time()
        total_segments = (file_size + 1024 - 1) // 1024   # Calculate how many segments the file will be split into
        segments_received = {}   # Dictionary to track which segments have been received
        bytes_received = 0   # Total number of bytes received so far
        last_received = time.time()   # Track the time of the last received segment

        while True:
            try:
                # Wait for data from the server
                received_data, _ = client_udp_socket.recvfrom(CONST_SIZE * 4)  # Maximum size of a segment (4KB)

                # Update the last receive time
                last_received = time.time()

                # Extract the header from the received data
                header_size = struct.calcsize('!IBQQ')  # Size of the header portion
                magic_cookie, message_type, total_segments, curr_segment = struct.unpack('!IBQQ', received_data[:header_size])

                # Validate the received data
                if magic_cookie != MAGIC_COOKIE or message_type != MTYPE_PAYLOAD:
                    print(Fore.WHITE + Back.RED + "Received data is invalid: Incorrect magic cookie or message type")
                    continue

                # Calculate the data size by subtracting the header size
                data_size = len(received_data) - header_size

                # Track the segment if it's the first time we've received it
                if curr_segment not in segments_received:
                    segments_received[curr_segment] = data_size   # Add segment to the dictionary so we can track it
                    bytes_received += data_size

                # Check if all segments are received or if enough time has passed to conclude the transfer
                if len(segments_received) >= total_segments or time.time() - last_received >= 1.5:
                    break

            except socket.timeout:
                # If there is a timeout but some data has been received, exit the loop
                if segments_received:
                    break

        # Calculate the transfer time and speed
        total_time = time.time() - start_time
        success_precent = (len(segments_received) / total_segments) * 100  # Percentage of successfully received packets
        trans_speed = (bytes_received * 8) / total_time  # Convert to bits per second

        # Print the results of the transfer as asked
        print(Fore.WHITE + Back.GREEN + f"UDP transfer #{connection_number} completed. "
                        f"Time taken: {total_time:.2f} seconds, "
                        f"Speed: {trans_speed:.1f} bits/second, "
                        f"Successful packets: {success_precent:.0f}%")

    except Exception as error:
        print(Fore.WHITE + Back.RED + f"Error in UDP connection #{connection_number}: {str(error)}")

    # Close the UDP socket when finished    
    finally:
        client_udp_socket.close()



def run_client():
    """
    Initiates the client, listens for server offers, and begins data transfers when receiving a valid offer.
    Each connection (TCP and UDP) is handled in a separate thread.
    """
    file_size, tcp_conn_num, udp_conn_num = values_from_user()  # Retrieve the requested values from the user

    while True:
        print(Fore.CYAN + Back.MAGENTA + "Client started, listening for offer requests...")

        # Wait for offer from a server and retrieve the necessary connection details
        server_ip, udp_port, tcp_port = find_server_offer()

        # List to hold all threads for concurrent connections
        connection_threads = []

        # Create a separate thread for each TCP connection
        for i in range(tcp_conn_num):
            thread = threading.Thread(target=manage_tcp_connection, args=(server_ip, tcp_port, file_size, i + 1))
            connection_threads.append(thread)
        
        # Create a separate thread for each UDP connection
        for i in range(udp_conn_num):
            thread = threading.Thread(target=manage_udp_connection, args=(server_ip, udp_port, file_size, i + 1))
            connection_threads.append(thread)

        # Start all threads
        for thread in connection_threads:
            thread.start()

        # Ensure that all threads complete before proceeding
        for thread in connection_threads:
            thread.join()

        # After completing all transfers, continue waiting for new offers
        print(Fore.CYAN + Back.MAGENTA + "All transfers complete, listening to offer requests")



if __name__ == "__main__":
    run_client()