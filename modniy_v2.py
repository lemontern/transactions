import time
from web3 import Web3
import asyncio
from flashbots import Flashbots
from concurrent.futures import ThreadPoolExecutor
import random

# Данные для подключения к сетям
networks = {
    'Ethereum': 'https://eth-mainnet.public.blastapi.io',
    'Polygon': 'https://polygon-rpc.com',
    'BNB': 'https://bsc-dataseed1.ninicoin.io/'
}

layer2_networks = {
    'Arbitrum': 'https://arbitrum-mainnet.infura.io/v3/YOUR_PROJECT_ID',
    'Optimism': 'https://optimism-mainnet.infura.io/v3/YOUR_PROJECT_ID'
}

backup_networks = {
    'Ethereum': ['https://mainnet.infura.io/v3/YOUR_PROJECT_ID', 'https://cloudflare-eth.com', 'https://rpc.flashbots.net'],
    'Polygon': ['https://rpc-mainnet.maticvigil.com', 'https://matic-mainnet.chainstacklabs.com', 'https://rpc-mainnet.matic.quiknode.pro'],
    'BNB': ['https://bsc-dataseed.binance.org/', 'https://bsc-dataseed1.defibit.io/', 'https://bsc-dataseed2.ninicoin.io/'],
    'Arbitrum': ['https://arb1.arbitrum.io/rpc', 'https://arbitrum-mainnet.infura.io/v3/YOUR_PROJECT_ID'],
    'Optimism': ['https://mainnet.optimism.io', 'https://optimism-mainnet.infura.io/v3/YOUR_PROJECT_ID']
}

wallet_addresses = [
    '0x4DE23f3f0Fb3318287378AdbdE030cf61714b2f3',
    '0xA4D023F2B033d9305Aa10829Aa213D6e392dA4f9'
]

private_keys = [
    'ee9cec01ff03c0adea731d7c5a84f7b412bfd062b9ff35126520b3eb3d5ff258',
    '1fbd9c01ff03c0adea731d7c5a84f7b412bff05cb9ff34126520b3eb3d7ff258'
]

receiver_address = '0x919eED6d00f330405a95Ee84fF22547171920cD1'
MINIMUM_BALANCE = 0.001
initial_gas_price = 200 * 10**9  # Начальный gas price в 200 Gwei
max_gas_price = 3000 * 10**9  # Максимальный gas price до 3000 Gwei
check_interval = 0.0001  # Минимальный интервал для частой проверки
max_parallel_txs = 30  # Максимум параллельных транзакций

# Функция для проверки и исправления EIP-55 формата адреса
def to_checksum_address(address):
    try:
        return Web3.to_checksum_address(address)
    except ValueError:
        print(f"Invalid address format: {address}")
        return None

# Подключение к сети с поддержкой резервных и альтернативных RPC
async def connect_to_network(network_name, network_url, backup_urls=None):
    try:
        web3 = Web3(Web3.HTTPProvider(network_url))
        if web3.is_connected():
            print(f"Connected to {network_name} via primary RPC: {network_url}")
            return web3
    except Exception as e:
        print(f"Primary network connection failed for {network_name}: {e}")
        # Попробовать подключиться к резервным RPC, если основной не работает
        if backup_urls:
            for url in backup_urls:
                try:
                    web3 = Web3(Web3.HTTPProvider(url))
                    if web3.is_connected():
                        print(f"Connected to {network_name} via backup RPC: {url}")
                        return web3
                except Exception as e:
                    print(f"Backup network connection failed for {network_name}: {e}")
    print(f"All connections failed for {network_name}, skipping.")
    return None

# Получение баланса
async def get_balance(web3, address):
    balance = web3.eth.get_balance(address)
    return web3.from_wei(balance, 'ether')

# Подготовка и отправка нескольких транзакций с агрессивными параметрами газа
async def prepare_and_send_multiple_transactions(web3, wallet_address, receiver_address, value, gas_price):
    nonce = web3.eth.get_transaction_count(wallet_address)
    bundles = []
    
    for i in range(max_parallel_txs):  # Отправляем до max_parallel_txs транзакций
        gas_price_step = gas_price + (i * random.randint(50, 150) * 10**9)  # Увеличиваем gas price на случайную величину в каждом шаге
        gas_price_step = min(gas_price_step, max_gas_price)  # Ограничиваем максимальное значение газа
        
        tx = {
            'nonce': nonce + i,
            'to': receiver_address,
            'value': web3.to_wei(value, 'ether'),
            'gas': 21000,
            'gasPrice': gas_price_step,  # Динамическое увеличение газа
        }
        signed_tx = web3.eth.account.sign_transaction(tx, private_keys[wallet_addresses.index(wallet_address)])
        bundles.append(signed_tx.rawTransaction)
    
    # Отправляем через Flashbots или fallback на публичный mempool
    await send_transaction_via_flashbots(web3, bundles)

# Отправка транзакции с использованием Flashbots с fallback на mempool
async def send_transaction_via_flashbots(web3, bundles):
    try:
        flashbots = Flashbots(web3, wallet_addresses[0])
        tx_hash = await flashbots.send_bundle(bundles, block_number=web3.eth.block_number + 1)
        print(f"Transaction bundle sent via Flashbots: {tx_hash.hex()}")
    except Exception as e:
        print(f"Error sending transaction via Flashbots: {e}")
        # Если Flashbots не сработали, отправляем напрямую в публичный mempool
        for raw_tx in bundles:
            try:
                tx_hash = web3.eth.send_raw_transaction(raw_tx)
                print(f"Fallback: Transaction sent via mempool: {tx_hash.hex()}")
            except Exception as mempool_error:
                print(f"Error sending transaction via mempool: {mempool_error}")

# Асинхронный мониторинг сети
async def monitor_network(network_name, network_url, wallet_address, backup_urls):
    web3 = await connect_to_network(network_name, network_url, backup_urls)
    
    # Если подключение не удалось, пропускаем мониторинг этой сети
    if web3 is None:
        return
    
    wallet_address = to_checksum_address(wallet_address)
    if wallet_address is None:
        return
    
    current_gas_price = initial_gas_price
    
    while True:
        try:
            balance = await get_balance(web3, wallet_address)
            if balance >= MINIMUM_BALANCE:
                print(f"Detected balance on {network_name} for {wallet_address}: {balance} ETH")
                await prepare_and_send_multiple_transactions(web3, wallet_address, receiver_address, balance, current_gas_price)
                current_gas_price += random.randint(50, 150) * 10**9  # Увеличиваем начальный gas price на случайную величину на следующий цикл
            else:
                print(f"Insufficient balance on {network_name} for {wallet_address}.")
        except Exception as e:
            print(f"Error on {network_name} for {wallet_address}: {e}")
        await asyncio.sleep(check_interval)  # Минимальный интервал для частой проверки

# Асинхронный запуск мониторинга всех сетей
async def monitor_all_networks():
    tasks = []
    with ThreadPoolExecutor() as executor:
        for wallet_address in wallet_addresses:
            for network_name, network_url in {**networks, **layer2_networks}.items():
                task = asyncio.create_task(monitor_network(
                    network_name,
                    network_url,
                    wallet_address,
                    backup_networks.get(network_name, None)
                ))
                tasks.append(task)
    await asyncio.gather(*tasks)

# Запуск скрипта
if __name__ == "__main__":
    print("Starting monitoring for all networks...")
    asyncio.run(monitor_all_networks())