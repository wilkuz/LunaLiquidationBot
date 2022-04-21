from time import sleep
from terra_sdk.client.lcd import LCDClient
from terra_sdk.key.mnemonic import MnemonicKey
from terra_sdk.client.lcd.api.tx import CreateTxOptions
from terra_sdk.core.wasm import MsgExecuteContract
from terra_sdk.core.market import MsgSwap
from terra_sdk.core.coins import Coins
from terra_sdk.core.coins import Coin
import os
from dotenv import load_dotenv
from datetime import datetime
import sys
import requests


network = 'columbus-5'
networkRPC = "https://lcd.terra.dev"

terra = LCDClient(networkRPC, network)
load_dotenv()
mn = os.environ.get("Mnemonic")
mk = MnemonicKey(mnemonic=mn)

ACTIVE_WALLET = MnemonicKey(mn)
ACTIVE_WALLET_ADRESS = mk.acc_address
ACTIVE_WALLET_PRIVATE_KEY = mk.private_key
ANC_LIQ_QUE_CONTRACT = "terra1e25zllgag7j9xsun3me4stnye2pcg66234je3u"
BLUNA_CONTRACT = "terra1kc87mu460fwkqte29rquh4hc20m54fxwtsx7gp"
BLUNA_LUNA_SWAP_CONTRACT = "terra1jxazgm67et0ce260kvrpfv50acuushpjsz2y0p"
BLUNA_UST_SWAP_CONTRACT = "terra1qpd9n7afwf45rkjlpujrrdfh83pldec8rpujgn"
LUNA_UST_SWAP_CONTRACT = "terra1tndcaqxkpc5ce9qee5ggqf430mr2z3pefe5wj6"
WALLET = terra.wallet(mk)

print(ACTIVE_WALLET_ADRESS)

# places bid in the Anc liquidation que with given collateral address and premium
def placeBid(symbolAdress, premium):
    currentBalance = terra.bank.balance(ACTIVE_WALLET_ADRESS)
    currentUSTBalance = int(round(currentBalance[0]["uusd"].amount))
    
    executeMsg = {"submit_bid": {
        "collateral_token": symbolAdress,
        "premium_slot": premium
    }}
    msg = MsgExecuteContract(ACTIVE_WALLET_ADRESS, ANC_LIQ_QUE_CONTRACT, execute_msg=executeMsg, coins={"uusd": int(currentUSTBalance-10000000)})
    print(f"attempting to submit bid of {(currentUSTBalance-10000000) / 1000000} UST")
    executeTx = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[msg], memo="place bid"))
    executeTxResult = terra.tx.broadcast(executeTx)
    print("submitBidHash:")
    print(executeTxResult.txhash)
    return executeTxResult.txhash

# gets the Anc liq que bid idx from a txhash
def getTxID(hash):
    reqURL = f"{networkRPC}/txs"
    txInfo = requests.get(f"{reqURL}/{hash}")
    txInfoJSON = txInfo.json()
    if txInfoJSON["logs"][0]["events"][3]["attributes"][2]["key"] == "bid_idx":
        return txInfoJSON["logs"][0]["events"][3]["attributes"][2]["value"]

# gets info about a bid idx
def getBidInfo(ID):
    bidInfo = terra.wasm.contract_query(ANC_LIQ_QUE_CONTRACT, {"bid": {"bid_idx": ID}})
    return bidInfo

# gets information about all bids from a certain address
def getBidsByUser(address):
    msg = {
    "bids_by_user": {
        "collateral_token": BLUNA_CONTRACT,
        "bidder": address, 
        "start_after": "123", 
        "limit": 30 
        }
    }
    bidsByUser = terra.wasm.contract_query(ANC_LIQ_QUE_CONTRACT, msg)
    IDs = []
    for bid in bidsByUser["bids"]:
        IDs.append(bid["idx"])
    return IDs

# returns the collateral symbol from bid information
def getTokenInfo(bidInfo):
    contract = bidInfo["collateral_token"]
    contractInfo = terra.wasm.contract_info(contract)
    return contractInfo["init_msg"]["symbol"], contract

# activates a bid that is ready
def activateBid(ID, adress):
    executeMsg = {"activate_bids": {
        "collateral_token": adress,
        "bids_idx": [ID]
    }}
    msg = MsgExecuteContract(ACTIVE_WALLET_ADRESS, ANC_LIQ_QUE_CONTRACT, execute_msg=executeMsg)
    print("attempting to activate bid")
    executeTx = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[msg], memo="activate bid"))
    executeTxResult = terra.tx.broadcast(executeTx)
    print("activated bid, txhash:")
    print(executeTxResult.txhash)

# claims pending liquidated collateral
def claimLiq(ID, symbolAdress):
    executeMsg = {"claim_liquidations": {
        "collateral_token": symbolAdress,
        "bids_idx": [ID]
    }}
    msg = MsgExecuteContract(ACTIVE_WALLET_ADRESS, ANC_LIQ_QUE_CONTRACT, execute_msg=executeMsg)
    print(f"attempting to claim/withdraw bid {ID}")
    executeTx = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[msg], memo="claim liq"))
    executeTxResult = terra.tx.broadcast(executeTx)
    print(f"withdrawal tx hash: {executeTxResult.txhash}")

# gets swaprate for bluna/luna
def getSwapRate():
    result = terra.wasm.contract_query(BLUNA_LUNA_SWAP_CONTRACT, {"simulation":{"offer_asset": {"amount": "1000000","info": {"token": {"contract_addr": BLUNA_CONTRACT}}}}})
    swapRate = result["return_amount"]
    return swapRate


if __name__ == "__main__":
    while True:
        connection = terra.tendermint.node_info()
        if not connection["default_node_info"]["network"] == network:
            print(connection)
            sys.exit("No connection could be made to network")
        else:
            premium = 3

            #get current bids IDs
            currentBids = getBidsByUser(ACTIVE_WALLET_ADRESS)
            if currentBids == []:
                placeBid(BLUNA_CONTRACT, premium)
                currentBids = getBidsByUser(ACTIVE_WALLET_ADRESS)
            for bid in currentBids:
                #query the contract with given bid ID
                currentBidInfo = getBidInfo(bid)
                currentBidToken, currentBidTokenAdress = getTokenInfo(currentBidInfo)

                #check if current bid is active
                if currentBidInfo["wait_end"] == None:
                    print(f"bid {bid} is active")
                    # if there is collateral to be withdrawn
                    if float(currentBidInfo["pending_liquidated_collateral"]) > 0:
                        print(f"withdrawal of {float(currentBidInfo['pending_liquidated_collateral']) / 1000} {currentBidToken} pending")
                        #withdraw tokens from contract
                        claimLiq(bid, currentBidTokenAdress)
                        
                        # swaps bLuna for Luna
                        BLunaBalance = terra.wasm.contract_query(BLUNA_CONTRACT, {"balance": {"address": ACTIVE_WALLET_ADRESS}})
                        swapAmount = str(BLunaBalance["balance"])
                        # in the following line, "msg": "eyJzd2FwIjoge319" is the string {"swap": {}} encoded to base64
                        send = MsgExecuteContract(ACTIVE_WALLET_ADRESS, BLUNA_CONTRACT, execute_msg={"send": {"contract": BLUNA_LUNA_SWAP_CONTRACT, "amount": swapAmount, "msg": "eyJzd2FwIjoge319"}})
                        executeTx = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[send], memo="swap bluna for luna"))
                        sendResult = terra.tx.broadcast(executeTx)
                        print("swapped bLuna for Luna")
                        print(sendResult.txhash)

                        # swap Luna for UST
                        balance = terra.bank.balance(ACTIVE_WALLET_ADRESS)
                        lunaBalance = balance[0]['uluna'].amount
                        coin = Coin("uluna", lunaBalance).to_data()
                        coins = Coins.from_data([coin])
                        swapToUst = MsgExecuteContract(ACTIVE_WALLET_ADRESS, LUNA_UST_SWAP_CONTRACT, execute_msg={"swap": {"offer_asset": {"info": {"native_token": {"denom": "uluna"}}, "amount": str(lunaBalance)}, "to": ACTIVE_WALLET_ADRESS}}, coins=coins)
                        executeSwap = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[swapToUst]))
                        swapResult = terra.tx.broadcast(executeSwap)
                        print("swapped Luna for UST")
                        print(swapResult.txhash)

                        #place new bid with UST
                        placeBid(BLUNA_CONTRACT, premium)

                    else:
                        print(f"waiting to be filled {str(round(int(currentBidInfo['amount']) / 1000000, 2))} USD remaining")
                elif datetime.utcfromtimestamp(currentBidInfo["wait_end"]) < datetime.utcnow():
                    print("ready to activate")
                    activateBid(bid, currentBidTokenAdress)
                else:
                    print(f"not ready, wait_end: {datetime.utcfromtimestamp(currentBidInfo['wait_end'])} UTC")
                    print()
                #query recent liquidation bid until it is filled
                #handle the response - if filled, withdraw and sell the bought amount, place another bid
                #save the bid id and use it for the next querys
                sleep(2)