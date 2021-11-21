import os, coloredlogs, logging, sys, time
import argparse, requests, csv, re, json


######################################################################################
# 0. Set-up environment
######################################################################################

# Set arguments to be parsed
parser = argparse.ArgumentParser(description="""Service Rasteator v1.0""")
parser.add_argument("--debug", "-d", dest="debug", choices=["on", "off"], default="off", 
                    help="Turn debugging mode on-off")
parser.add_argument("--nodes", "-n", dest="nodes",
                    help="Nodes list in CSV exported from 360 tool")

# Check & set args
args = parser.parse_args()

# Debug Set
def str_to_bool(s):
    if s == "on":
         return False
    elif s == "off":
         return True
    else:
         raise ValueError
    return

# Set debug environment
def logging_set(args):
    handler = logging.StreamHandler()
    handler.addFilter(coloredlogs.HostNameFilter())
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    logger=logging.getLogger()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.disabled=str_to_bool(args.debug)
    logging.debug(args)
    coloredlogs.install(level="DEBUG", logger=logger)
    return

######################################################################################
# 1. Request latest commited config
######################################################################################
def get_conf(node_info):
    url_version = str("https://ispdomain.com/admin/inventory/oxidized/node/version/"+node_info[2]+"/"+node_info[0]+"?draw=1&_=*")
    https_headers = {"PHPSESSID":"key",
        "REMEMBERME":"cookie"
        }

    # First find configuration history and get the latest one
    try:
        node_conf_vers = requests.get(url_version, cookies=https_headers)
        if node_conf_vers.text == "<Response [200]>":
            if json.loads(node_conf_vers.text)["data"]:
                last_config = json.loads(node_conf_vers.text)["data"][0]

                # Get the latest found configuration from oxidized
                url_conf = "https://ispdomain.com/admin/inventory/oxidized/node/config/"+node_info[2]+"/"+last_config["oid"]+"/"+node_info[0]
                try:
                    node_conf = requests.get(url_conf, cookies=https_headers)
                    """ time.sleep(1) """
                except requests.exceptions.HTTPError as e:
                    # Whoops it wasn"t a 200
                    logging.debug( "[Error: " + str(e))
                    return "Error_get"

                return str(node_conf.text).replace("<br />", "")
            else:
                return "Empty"
        else:
            return "Empty"
    except requests.exceptions.HTTPError as e:
        # Whoops it wasn"t a 200
        logging.debug( "[Error: " + str(e))
        return "Error_get"

######################################################################################
# 2. EXTRACT ALL CONFGIURED INTERFACES
######################################################################################
def parse_conf(node_info, node_conf_arr):
    data={
        "node_info":node_info,
        "if_arr":[],
        "if_shutd":[],
        "if_pw":[],
        "if_evpn":[],
        "if_uplink":[],
        "if_lo0":"",
        "if_lo1":"",
        "if_lag":[],
        "evpn_all":[],
        "evpl_all":[],
    }
    if_ul={}

    # 1- Search and save all EVPN & EVPL & INTERFACES on configuration
    for item in node_conf_arr:
        if item.startswith("evpn vpn-instance") and item.endswith("vpws"):
            found_evpn=node_conf_arr.index(item)
            for item_delimiter in node_conf_arr[found_evpn:]:
                if item_delimiter.startswith("#"):
                    found_delimiter=node_conf_arr[found_evpn:].index(item_delimiter)
                    data["evpn_all"].append(node_conf_arr[found_evpn:found_evpn+found_delimiter])
                    break
        elif item.startswith("evpl instance") and item.endswith("mpls-mode"):
            found_evpl=node_conf_arr.index(item)
            for item_delimiter in node_conf_arr[found_evpl:]:
                if item_delimiter.startswith("#"):
                    found_delimiter=node_conf_arr[found_evpl:].index(item_delimiter)
                    data["evpl_all"].append(node_conf_arr[found_evpl:found_evpl+found_delimiter])
                    break
        elif item.startswith("interface"):
            if "Eth-Trunk" in item or "GigabitEthernet" in item or "LoopBack" in item:
                found_ind=node_conf_arr.index(item)
                for item_delimiter in node_conf_arr[found_ind:]:
                    if item_delimiter.startswith("#"):
                        found_delimiter=node_conf_arr[found_ind:].index(item_delimiter)
                        data["if_arr"].append(node_conf_arr[found_ind:found_ind+found_delimiter])
                        break

    # 2- Filter which ones are not in use ("shutdown")
    for interface in data["if_arr"]:
        for element in interface:
            if element.startswith("shutdown"):
                data["if_shutd"].append(interface)
                break
    [data["if_arr"].remove(del_if) for del_if in data["if_shutd"]]

    # 3- Filter which ones carry service and which belong to LAG
    for interface in data["if_arr"]:
        uplink=""
        if_ul={}
        for element in interface:
            if element.startswith("mpls l2vc"):
                data["if_pw"].append(interface)
                break
            elif element.startswith("evpl instance"):
                data["if_evpn"].append(interface)
                break
            elif "LoopBack0" in interface[0].split(" ")[1]:
                for ele in interface:
                    if ele.startswith("ip address"):
                        data["if_lo0"] = ele.split(" ")[2]
                break
            elif "LoopBack1" in interface[0].split(" ")[1]:
                for ele in interface:
                    if ele.startswith("ip address"):
                        data["if_lo1"] = ele.split(" ")[2]
                break

            # Uplink detection by priority
            elif element.startswith("ip address"):
                if_ul["interface"] = interface[0].split(" ")[1]
                if_ul["if_uplink_mode"] = "L3 interface"
                uplink="set"
            elif element.startswith("port trunk allow-pass"):
                if_ul["interface"] = interface[0].split(" ")[1]
                if "74" in element:
                    if_ul["if_uplink_mode"] = "L2 port trunk - MPLS"
                    if_ul["if_uplink_vlan"] = "74"
                uplink="set"
            elif (interface[0].split(" ")[1] == "Eth-Trunk24" or interface[0].split(" ")[1] == "Eth-Trunk25") and (element.startswith("port trunk allow-pass")):
                if_ul["interface"] = interface[0].split(" ")[1]
                if_ul["if_uplink_mode"] = "L2 port trunk - No_MPLS"
                uplink="set"
            elif (interface[0].split(" ")[1] == "Eth-Trunk24" or interface[0].split(" ")[1] == "Eth-Trunk25") and (element.startswith("port default vlan")):
                if_ul["interface"] = interface[0].split(" ")[1]
                if_ul["if_uplink_mode"] = "L2 port access"
                if_ul["if_uplink_vlan"] = element.split(" ")[3]
                uplink="set"
            elif element.startswith("eth-trunk"):
                data["if_lag"].append(interface)
                break

        if uplink == "set":
            for element in interface:
                if element.startswith("description"):
                    spplt_ele=element.split(" ")
                    spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                    spplt_ele_2=list(filter(None, spplt_ele_2))
                    for each in spplt_ele_2:
                        if each.startswith("RE"):
                            if_ul["uplink_re"] = each.split("=")[1]
                        if each.startswith("RI"):
                            if_ul["uplink_ri"] = each.split("=")[1]
            if ("uplink_re" in if_ul) and ("OLT" not in if_ul["uplink_re"]):
                data["if_uplink"].append(if_ul.copy())
            else:
                data["if_uplink"].append(if_ul.copy())

    
    return(data)

######################################################################################
# 3. PARSE SERVICES DATA INTO STRUCTURED INFO
######################################################################################
def parse_services_data(data):
    main_vula_if=[]
    pw_data={
        "interface":"",
        "service":"",
        "mtu":"",
        "uplink":"",
        "main_pw_re":"",
        "main_pw_ip":"",
        "main_pw_vcid":"",
        "secondary_pw_re":"",
        "secondary_pw_ip":"",
        "secondary_pw_vcid":"",
        "vri":"",
        "olt":"",
        "vlan_olt":"",
        "vlan_mapped":[],
        "adm_lag":[],
        "lag_members":[],
    }
    evpn_data={
        #"lag_members":[],
    }
    service_data={
        "node_code":str(node_info[2]),
        "node_location":str(node_info[6]),
        "node_ip":str(data["if_lo1"]),
        "loopback0":str(data["if_lo0"]),
        "node_monitored":str(node_info[7]),
        "node_model":str(node_info[5]),
        "pw_data":[],
        "evpn_data":[],
    }

    # FALTA SACAR MIEMBROS LAG DE INTERFAZ ACCESO #
    # 1- Extract PW information
    for interface in data["if_pw"]:
        pw_data["interface"]=interface[0].split(" ")[1]
        pw_data["uplink"]=data["if_uplink"]
        
        for if_all in data["if_lag"]:
            if "GigabitEthernet" in if_all[0] and not "." in if_all[0]:
                for element in if_all:
                    if element.startswith("eth-trunk "):
                        if element.replace(" ", "") == interface[0].lower().split(" ")[1].split(".")[0]:
                            pw_data["lag_members"].append(if_all[0].split(" ")[1])

        for element in interface:
            if element.startswith("mtu"):
                spplt_ele=element.split(" ")
                pw_data["mtu"]=spplt_ele[1]
            # Filter Main PW
            elif element.startswith("mpls l2vc") and not element.endswith("secondary"):
                spplt_ele=element.split(" ")
                pw_data["main_pw_ip"]=spplt_ele[2]
                pw_data["main_pw_vcid"]=spplt_ele[3]
            # Filter Secondary PW
            elif element.startswith("mpls l2vc") and element.endswith("secondary"):
                spplt_ele=element.split(" ")
                pw_data["secondary_pw_ip"]=spplt_ele[2]
                pw_data["secondary_pw_vcid"]=spplt_ele[3]
            # Filter Mapping info
            elif element.startswith("qinq mapping"):
                spplt_ele=element.split(" ")
                pw_data["vlan_olt"]=spplt_ele[3]
                pw_data["vlan_mapped"]=spplt_ele[6]
            # Filter Description
            elif element.startswith("description"):
                spplt_ele=element.split(" ")
                spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                spplt_ele_2=list(filter(None, spplt_ele_2))
                for each in spplt_ele_2:
                    if each.startswith("VRE"):
                        if pw_data["main_pw_re"] == "":
                            pw_data["main_pw_re"]=each.split("=")[1]
                        elif pw_data["secondary_pw_re"] == "":
                            pw_data["secondary_pw_re"]=each.split("=")[1]
                    elif each.startswith("VRI"):
                        pw_data["vri"]=each.split("=")[1]
                    elif each.startswith("SRV1"):
                        pw_data["service"]=each.split("=")[1]
                        if "NEBA" in each.split("=")[1]:
                            main_if=str("interface "+pw_data["interface"].split(".")[0])
                            for interface in data["if_arr"]:
                                if interface[0] == main_if:
                                    for element in interface:
                                        if element.startswith("description"):
                                            spplt_ele=element.split(" ")
                                            spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                                            spplt_ele_2=list(filter(None, spplt_ele_2))
                                            for each in spplt_ele_2:
                                                if each.startswith("ADM_LAG"):
                                                    pw_data["adm_lag"]=each.split("=")[1]
                        elif "VULA" in each.split("=")[1]:
                            for interface in data["if_arr"]:
                                if not "." in interface[0] and "Eth-Trunk" in interface[0]:
                                    for element in interface:
                                        if element.startswith("interface"):
                                            main_if=element
                                        if element.startswith("description") and "VULA" in element:
                                            main_vula_if.append(main_if)
                                            spplt_ele=element.split(" ")
                                            spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                                            spplt_ele_2=list(filter(None, spplt_ele_2))
                                            for each in spplt_ele_2:
                                                if each.startswith("ADM_LAG"):
                                                    pw_data["adm_lag"].append(each.split("=")[1])                        
                            for interface in data["if_arr"]:
                                for main_if in main_vula_if:
                                    if main_if in interface[0] and "." in interface[0]:
                                        for element in interface:
                                            if element.startswith("rewrite map 2-to-2"):
                                                vlan_mapped=element.split(" ")[4]
                                                if vlan_mapped not in pw_data["vlan_mapped"]:
                                                    pw_data["vlan_mapped"].append(vlan_mapped)
                        else: #if "VDF" in each.split("=")[1] or "FTTH-VDF" in each.split("=")[1] or "ORANGE" in each.split("=")[1] or "MM" in each.split("=")[1]or "MM" in each.split("=")[1]:
                            main_if=interface[0].split(" ")[1].split(".")[0]
                            for interface in data["if_arr"]:
                                if not "." in interface[0] and main_if in interface[0]:
                                    for element in interface:
                                        if element.startswith("description"):
                                            main_vula_if.append(main_if)
                                            spplt_ele=element.split(" ")
                                            spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                                            spplt_ele_2=list(filter(None, spplt_ele_2))
                                            for each in spplt_ele_2:
                                                if each.startswith("RE"):
                                                    pw_data["olt"]=each.split("=")[1]

        service_data["pw_data"].append(pw_data.copy())
        pw_data.clear()
        pw_data={
            "interface":"",
            "service":"",
            "mtu":"",
            "uplink":"",
            "main_pw_re":"",
            "main_pw_ip":"",
            "main_pw_vcid":"",
            "secondary_pw_re":"",
            "secondary_pw_ip":"",
            "secondary_pw_vcid":"",
            "vri":"",
            "olt":"",
            "vlan_olt":"",
            "vlan_mapped":[],
            "adm_lag":[],
            "lag_members":[],
        }

    evpn_data={
            "adm_lag": "",
            "evpl_instance": "",
            "evpn_instance":"",
            "evpn_rd": "",
            "evpn_rt": "",
            "interface": "",
            "local_service_id": "",
            "main_evpn_re": "",
            "offset": "",
            "remote_service_id": "",
            "secondary_evpn_re": "",
            "service": "",
            "uplink": [],
            "vlan_mapping": "",
            "vlan_tesa_range": "",
            "vri": "",
            "lag_members":[],
        }

    # 2- Extract eVPN information
    for interface in data["if_evpn"]:
        evpn_data["interface"]=interface[0].split(" ")[1]
        evpn_data["uplink"]=data["if_uplink"]

        for if_all in data["if_lag"]:
            if "GigabitEthernet" in if_all[0] and not "." in if_all[0]:
                for element in if_all:
                    if element.startswith("eth-trunk "):
                        if element.replace(" ", "") == interface[0].lower().split(" ")[1].split(".")[0]:
                            evpn_data["lag_members"].append(if_all[0].split(" ")[1])

        for element in interface:
            if element.startswith("encapsulation dot1q"):
                spplt_ele=element.split(" ")
                evpn_data["vlan_tesa_range"]=str(spplt_ele[3]+"-"+spplt_ele[5])
            # Filter Offset
            elif element.startswith("rewrite map"):
                spplt_ele=element.split(" ")
                if spplt_ele[3] == "increase":
                    evpn_data["offset"]=str("+"+spplt_ele[4])
                    tesa_range=evpn_data["vlan_tesa_range"].split("-")
                    evpn_data["vlan_mapping"]=str(int(tesa_range[0])+int(spplt_ele[4]))+"-"+str(int(tesa_range[1])+int(spplt_ele[4]))
                else:
                    evpn_data["offset"]=str("-"+spplt_ele[4])
                    tesa_range=evpn_data["vlan_tesa_range"].split("-")
                    evpn_data["vlan_mapping"]=str(int(tesa_range[0])-int(spplt_ele[4]))+"-"+str(int(tesa_range[1])-int(spplt_ele[4]))
            # Filter EVPL / EVPN
            elif element.startswith("evpl instance"):
                spplt_ele=element.split(" ")
                evpn_data["evpl_instance"]=spplt_ele[2]
                for evpl in data["evpl_all"]:
                    evpl_id=evpl[0].split(" ")
                    if evpl_id[2] == spplt_ele[2]:
                        evpl_serv=evpl[2].split(" ")
                        evpl_evpn=evpl[1].split(" ")
                        evpn_data["local_service_id"]=evpl_serv[1]
                        evpn_data["remote_service_id"]=evpl_serv[3]
                        for evpn in data["evpn_all"]:
                            if len(evpn)>0:
                                evpn_id=evpn[0].split(" ")
                                if evpn_id[2] == evpl_evpn[3]:
                                    evpn_data["evpn_instance"]=evpn_id[2]
                                    evpn_data["evpn_rd"]=evpn[1].split(" ")[1].split(":")[1]
                                    evpn_data["evpn_rt"]=evpn[2].split(" ")[1].split(":")[1]
            # Filter Description
            elif element.startswith("description"):
                spplt_ele=element.split(" ")
                spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                spplt_ele_2=list(filter(None, spplt_ele_2))
                for each in spplt_ele_2:
                    if each.startswith("VRE"):
                        
                        try:
                            if evpn_data["main_evpn_re"] == "":
                                evpn_data["main_evpn_re"]=each.split("=")[1]
                            else:
                                evpn_data["secondary_evpn_re"]=each.split("=")[1]
                        except:
                            evpn_data["main_evpn_re"]=each.split("=")[1]
                    elif each.startswith("VRI"):
                        evpn_data["vri"]=each.split("=")[1]
                    elif each.startswith("SRV1"):
                        evpn_data["service"]=each.split("=")[1]
                        if "NEBA" in each.split("=")[1]:
                            main_if=str("interface "+evpn_data["interface"].split(".")[0])
                            for interface in data["if_arr"]:
                                if interface[0] == main_if:
                                    for element in interface:
                                        if element.startswith("description"):
                                            spplt_ele=element.split(" ")
                                            spplt_ele_2=re.split("&amp;lt;|&amp;gt;", spplt_ele[1])
                                            spplt_ele_2=list(filter(None, spplt_ele_2))
                                            for each in spplt_ele_2:
                                                if each.startswith("ADM_LAG"):
                                                    evpn_data["adm_lag"]=each.split("=")[1]
        service_data["evpn_data"].append(evpn_data.copy())
        evpn_data.clear()
        
        evpn_data={
                "adm_lag": "",
                "evpl_instance": "",
                "evpn_instance":"",
                "evpn_rd": "",
                "evpn_rt": "",
                "interface": "",
                "local_service_id": "",
                "main_evpn_re": "",
                "offset": "",
                "remote_service_id": "",
                "secondary_evpn_re": "",
                "service": "",
                "uplink": [],
                "vlan_mapping": "",
                "vlan_tesa_range": "",
                "vri": "",
                "lag_members":[],
            }

    
    return service_data

######################################################################################
# 3. Export results to csv file
######################################################################################
def export_parsed_results(service_inventory):
    parsed_header = ["Id_Service","Code_Service","Observations","Config_State","MPLS_Service","Type","Code_Service","OLT_Name","OLT_Location","CMT","Code_Service","Type","Central_Type","NMIGA","Population","Administrative","Code_Service","Name_OBA_ATN","Management","Loopback0_ATN","Access_Equipment_MSW_ABR_LER","MSW-ABR-LER_Zona","ATN_Log_INTF","ATN_Phy_INTF_1","ATN_Phy_INTF_2","ATN_Phy_INTF_3","ATN_Phy_INTF_4","VLAN_OLT","VLAN_Mapping","ATN_Log_UPLINK","Observations","Code_Service","Service_Icx_3rd","Termination_BRAS","RES_Act_Gw_Name","RES_Act_Gw_Log_INTF","CORP_Act_Gw_LT_INTF","CORP_Act_Gw_PS_INTF","RES_Act_Gw_VCID","RES_Bck_Gw_Name","RES_Bck_Gw_Log_INTF","CORP_Bck_Gw_LT_INTF","CORP_Bck_Gw_PS_INTF","RES_Bck_Gw_VCID","RES_Act_BRAS_Name","RES_Act_BRAS_Log_INTF","RES_Bck_BRAS_Name","RES_Bck_BRAS_Log_INTF","BAS_Interface","Observations","Code_Service","EVPN_Instance","RD","RT","EVPL_Instance","Local_Service_ID","Remote_Service_ID","VLANs_TESA_Range","Vlan_Mapping","Offset","LER_Act","AE_Interface","CBR_Act","Eth-trunk","LER_Bck","AE_Interface2","CBR_bck","Eth-trunk3","BAS_Interface"]
    t = time.localtime()
    timestamp = time.strftime("Service_report_%b-%d-%Y_%H%M", t)
    csvfile = "out/" + timestamp + "_out.csv"
    uplink_select = {"uplink_re":""}
    index=1

    # Complete parsed string correspondence for all parameters on JSON (PW_DATA + EVPN_DATA)
    # parsed_service=str(index)+","+str(code_service)+",,"+deploy_stat+","+"PWHT"+","+str(service["service"])+","+str(code_service)+","+str(service["olt"])+",,,"+str(code_service)+","+str(service["service"])+",,,,"+str(service["adm_lag"]).replace(",", ";")+","+str(code_service)+","+str(ATN["node_code"])+","+str(ATN["node_ip"])+","+str(ATN["loopback0"])+","+str(acc_node_no_sac)+","+str(uplink_select["uplink_re"])+","+str(serv_int_main)+","+str(",".join(service["lag_members"]))+","+str(service["vlan_olt"])+","+str(service["vlan_mapped"])+","+str(uplink_select["interface"])+",,"+str(code_service)+",,,"+str(service["main_pw_re"])+",,,,"+str(service["main_pw_vcid"])+","+str(service["secondary_pw_re"])+",,,,"+str(service["secondary_pw_vcid"])+",,,,,,,"+str(code_service)+","+str(service["evpn_instance"])+","+str(service["evpn_rd"])+","+str(service["evpn_rt"])+","+str(service["evpl_instance"])+","+str(service["local_service_id"])+","+str(service["remote_service_id"])+","+str(service["vlan_tesa_range"])+","+str(service["vlan_mapping"])+","+str(service["offset"])+","+str(service["main_evpn_re"])+",,,,"+str(service["secondary_evpn_re"])+",,,,,"

    with open(csvfile, "a") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([",".join(parsed_header)])
        
        for ATN in service_inventory:
            atn_service=1

            # Is an access node?
            if not "SAC" in ATN["node_code"].split("-")[1]:
                acc_node_no_sac="VERDADERO"
            else:
                acc_node_no_sac="FALSO"

            # Is it deployed?
            if ATN["node_ip"] == "Huawei despues":
                deploy_stat="Pte.Configurar"
            else:
                deploy_stat="Configurado"

            for service in ATN["pw_data"]:
                code_service=ATN["node_code"]+"-"+str(atn_service)
                serv_int_main=service["interface"].split(".")[0]
                # Uplink Interface > Filter if more than 1 exists
                
                if len(service["uplink"]) > 1:
                    for up_trunk in service["uplink"]:
                        try:
                            if "L3" in up_trunk["if_uplink_mode"]:
                                uplink_select=up_trunk
                                break
                            else: #
                                if up_trunk["if_uplink_vlan"]:
                                    if "74" in up_trunk["if_uplink_vlan"]:
                                        uplink_select=up_trunk
                                        break
                                else:
                                    uplink_select["uplink_re"]="check_uplink_no_mode"
                                    break
                        except:
                            uplink_select["uplink_re"]="check_uplink_no_mode"
                else:
                    try:
                        uplink_select=service["uplink"][0]
                    except:
                        uplink_select["uplink_re"]="no_uplink_detected"
                # Split service lag members
                if len(service["lag_members"]) < 4:
                    size_arr=4-len(service["lag_members"])
                    service["lag_members"].extend(["" for x in range(size_arr)])
                # Parse PW
                parsed_service=str(index)+","+str(code_service)+",,"+deploy_stat+","+"PWHT"+","+str(service["service"])+","+str(code_service)+","+str(service["olt"])+",,,"+str(code_service)+","+str(service["service"])+","+""+",,,"+str(service["adm_lag"]).replace(",", ";")+","+str(code_service)+","+str(ATN["node_code"])+","+str(ATN["node_ip"])+","+str(ATN["loopback0"])+","+str(acc_node_no_sac)+","+str(uplink_select["uplink_re"])+","+str(serv_int_main)+","+str(",".join(service["lag_members"]))+","+str(service["vlan_olt"])+","+str(service["vlan_mapped"]).replace(",", ";")+","+str(uplink_select["interface"])+",,"+str(code_service)+",,,"+str(service["main_pw_re"])+",,,,"+str(service["main_pw_vcid"])+","+str(service["secondary_pw_re"])+",,,,"+str(service["secondary_pw_vcid"])

                writer.writerow([parsed_service])
                atn_service+=1
                index+=1

            
            for service in ATN["evpn_data"]:
                code_service=ATN["node_code"]+"-"+str(atn_service)
                serv_int_main=service["interface"].split(".")[0]
                # Uplink Interface > Filter if more than 1 exists
                if len(service["uplink"]) > 1:
                    for up_trunk in service["uplink"]:
                        try:
                            if "L3" in up_trunk["if_uplink_mode"]:
                                uplink_select=up_trunk
                                break
                            else: #
                                if up_trunk["if_uplink_vlan"]:
                                    if "74" in up_trunk["if_uplink_vlan"]:
                                        uplink_select=up_trunk
                                        break
                                else:
                                    uplink_select["uplink_re"]="check_uplink_no_mode"
                                    break
                        except:
                            uplink_select["uplink_re"]="check_uplink_no_mode"
                else:
                    try:
                        uplink_select=service["uplink"][0]
                    except:
                        uplink_select["uplink_re"]="no_uplink_detected"
                # Split service lag members
                if len(service["lag_members"]) < 4:
                    size_arr=4-len(service["lag_members"])
                    service["lag_members"].extend(["" for x in range(size_arr)])

                # Parse EVPN
                parsed_service=str(index)+","+str(code_service)+",,"+deploy_stat+","+"EVPN"+","+str(service["service"])+","+str(code_service)+","+",,,"+str(code_service)+","+str(service["service"])+","+"offset"+",,,"+str(service["adm_lag"]).replace(",", ";")+","+str(code_service)+","+str(ATN["node_code"])+","+str(ATN["node_ip"])+","+str(ATN["loopback0"])+","+str(acc_node_no_sac)+","+str(uplink_select["uplink_re"])+","+str(serv_int_main)+","+str(",".join(service["lag_members"]))+","+","+","+str(uplink_select["interface"])+",,"+",,,"+",,,,"+","+",,,,"+",,,,,,,"+str(code_service)+","+str(service["evpn_instance"])+","+str(service["evpn_rd"])+","+str(service["evpn_rt"])+","+str(service["evpl_instance"])+","+str(service["local_service_id"])+","+str(service["remote_service_id"])+","+str(service["vlan_tesa_range"])+","+str(service["vlan_mapping"])+","+str(service["offset"])+","+str(service["main_evpn_re"])+",,,,"+str(service["secondary_evpn_re"])+",,,,,"
                writer.writerow([parsed_service])
                atn_service+=1
                index+=1




if __name__ == "__main__":
    logging_set(args)
    node_info_list = []
    service_inventory=[]

    with open(args.nodes, "r") as node:
        node_list = node.readlines()
        for node_line in node_list:
            node_info_list.append(node_line.split(";"))


    for node_info in node_info_list:
        if node_info[7] == "SI" and node_info[5][:3] == "ATN":
            node_conf = get_conf(node_info)
            if node_info != "Empty":
                if node_conf == "Error_get" or node_info[4] != "Huawei":
                    pass
                else:
                    node_conf_arr = list(map(str.strip, node_conf.splitlines()))
                    node_conf_parsed = parse_conf(node_info, node_conf_arr)
                    service_inventory.append(parse_services_data(node_conf_parsed).copy())
        else:
            pass
    
    #print(service_inventory)
    print(json.dumps(service_inventory, indent=2, sort_keys=True))
    export_parsed_results(service_inventory)
    logging.debug("[Finised -- OK]")
