from time import sleep
from terra_sdk.client.lcd import LCDClient
from terra_sdk.key.mnemonic import MnemonicKey
from terra_sdk.client.lcd.api.tx import CreateTxOptions
from terra_sdk.core.wasm import MsgExecuteContract
from terra_sdk.core.market import MsgSwap
from terra_sdk.core.coins import Coins
from terra_sdk.core.coins import Coin
from datetime import datetime
from dotenv import load_dotenv
import sys
import requests
import json
import base64
import os


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
#Astroport contracts
ASTROPORT_ROUTER = "terra16t7dpwwgx9n3lq6l6te3753lsjqwhxwpday9zx"

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

if __name__ == "__main__":
    while True:
        connection = terra.tendermint.node_info()
        if not connection["default_node_info"]["network"] == network:
            print(connection)
            sys.exit("No connection could be made to network")
        else:
            premium = 1

            #if wallet balance is above 50USD, place bid
            USTBalance = terra.bank.balance(ACTIVE_WALLET_ADRESS)[0]["uusd"].amount
            if USTBalance > 50000000:
                placeBid(BLUNA_CONTRACT, premium)

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

                        ## swap bLuna to Luna on Astroport ##

                        BLunaBalance = terra.wasm.contract_query(BLUNA_CONTRACT, {"balance": {"address": ACTIVE_WALLET_ADRESS}})
                        swapAmount = BLunaBalance["balance"]
                        minReceive = round(int(swapAmount) * 0.95)
                        astroMsg = {
                        "execute_swap_operations":
                        {
                            "offer_amount":swapAmount,
                            "operations":[{
                            "astro_swap":{
                                "offer_asset_info":{
                                "token":{
                                    "contract_addr":BLUNA_CONTRACT
                                    }
                                },
                                "ask_asset_info":{
                                    "native_token":{
                                    "denom":"uluna"
                                    }
                                }
                                }
                            },
                            {
                            "astro_swap":{
                                    "offer_asset_info":{
                                    "native_token":{
                                        "denom":"uluna"
                                        }
                                    },
                                    "ask_asset_info":{
                                        "native_token":{
                                        "denom":"uusd"
                                        }
                                        }
                                    }
                                    }],
                                    "minimum_receive":str(minReceive),"max_spread":"0.15"
                                    }
                                }
                        # encode to base64 for Astro router
                        message_bytes = json.dumps(astroMsg).replace(" ", "").encode('utf-8')
                        base64_bytes = base64.b64encode(message_bytes)
                        base64_message = base64_bytes.decode('utf-8')
                        sendMsg = {
                            "send": {
                                "amount": swapAmount,
                                "contract": ASTROPORT_ROUTER,
                                "msg": base64_message
                            }
                        }
                        print("swapping bLuna to UST on Astroport")
                        swapToUST = MsgExecuteContract(ACTIVE_WALLET_ADRESS, BLUNA_CONTRACT, execute_msg=sendMsg)
                        executeSwap = WALLET.create_and_sign_tx(CreateTxOptions(msgs=[swapToUST]))
                        result = terra.tx.broadcast(executeSwap)
                        print(result.txhash)

                        #place new bid with UST
                        placeBid(BLUNA_CONTRACT, premium)

                    else:
                        print(f"waiting to be filled {str(round(int(currentBidInfo['amount']) / 1000000, 2))} USD remaining in the {premium}% pool")
                elif datetime.utcfromtimestamp(currentBidInfo["wait_end"]) < datetime.utcnow():
                    print("ready to activate")
                    activateBid(bid, currentBidTokenAdress)
                else:
                    print(f"not ready, wait_end: {datetime.utcfromtimestamp(currentBidInfo['wait_end'])} UTC")
                    print()
                #query recent liquidation bid until it is filled
                #handle the response - if filled, withdraw and sell the bought amount, place another bid
                #save the bid id and use it for the next querys
                sleep(1)
