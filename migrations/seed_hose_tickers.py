#!/usr/bin/env python3
"""Seed Vietnam (HOSE + HNX) tickers into datapai.ticker_universe and stock_directory."""
import psycopg2
import psycopg2.extras
import os

# 400+ HOSE tickers from stockanalysis.com
HOSE_TICKERS = """VIC,VCB,VHM,BID,CTG,TCB,MBB,HPG,GAS,VPB,MCH,VPL,BSR,VNM,FPT,LPB,HDB,TCX,ACB,GVR,STB,MWG,MSN,VJC,VCK,SHB,SSI,HVN,VRE,BVH,VIB,SAB,VPX,GEE,BCM,PLX,SSB,TPB,EIB,POW,PNJ,REE,MSB,GMD,GEX,OCB,VCI,NVL,PGV,KDH,FRT,KBC,VIX,DCM,VND,NAB,HCM,DGC,DPM,HAG,PVD,VGC,SBT,VPI,CRV,TAL,DXG,PDR,SJS,KDC,TCH,VCG,SIP,DHG,NLG,VHC,LGC,CII,HDG,PC1,BAF,VSH,DIG,VTP,PVT,BMP,EVF,BWE,CTR,DGW,VSC,HSG,DBC,HAH,IMP,KOS,CTD,VCF,FTS,DSE,BSI,VAB,PHR,ORS,KLB,TMS,NT2,BHN,CMG,IJC,TDM,PAN,PDN,NKG,ANV,GEG,HHV,HT1,HNA,ACG,CTS,SZC,SCS,DBD,BIC,HHS,DPG,TLG,CHP,PET,DCL,TMP,MSH,MIG,VDS,STG,PPC,SHP,QCG,DXS,NTC,DSC,HDC,DPR,DHC,CRE,AST,PTB,BFC,AGR,NAF,CSV,TRA,MCM,DVP,TDP,TVS,AAA,VPD,VVS,TCM,BMI,SHI,TV2,NCT,SCR,PGD,SAM,FMC,KHG,SGT,BCG,TBC,PGI,ASM,VFG,TTA,STK,LIX,RAL,AGG,DRC,HRC,TRC,DMC,YEG,LCG,NTL,FCN,ELC,KSB,IDI,CTF,NBB,VOS,SGN,PAC,SBA,SVC,TNH,SRC,PVP,ASG,HTG,OPC,S4A,HQC,FIT,CKG,TDC,HPX,CLC,THG,LHG,CTI,APH,GHC,ACC,TIX,QNP,SZL,GIL,NSC,APG,EVG,CSM,LBM,TIP,NNC,VDP,NHH,SMB,CDC,HHP,D2D,HAX,CLL,TCL,SGR,ITC,TTF,TCI,TTE,SJD,TN1,VTO,CVT,DC4,OGC,CNG,ILB,LDG,PGC,HAP,ANT,SMC,VIP,TVB,GSP,LSS,HVH,DLG,TEG,PDV,VAF,ABT,DHA,DTL,CRC,VNG,NVT,TSA,SFI,FDC,VRC,ACL,KHP,TCD,TLD,CLW,SKG,CMX,ADS,HTI,NHA,SBG,ICT,VNS,DAT,TNC,BTT,HTN,MCP,ADP,TYA,BTP,SFG,UIC,TLH,JVC,TSC,RYG,PLP,GDT,DSN,COM,TMT,TNT,CCI,DRL,EVE,ITD,HUB,MHC,MDG,TDH,BCE,TDW,TCO,VPG,HII,SSC,FIR,VSI,AFX,VNE,HID,C47,SAV,PMG,VPH,C32,TVT,YBM,CCC,CIG,HMC,HAR,DRH,HCD,PNC,CCL,VNL,LAF,PTL,HTL,NHT,TCT,DQC,LGL,DAH,L10,DBT,SRF,ABS,PHC,SC5,DHM,ABR,VMD,PJT,SFC,TNI,SMA,SBV,AAT,VPS,PTC,VID,SVT,ADG,HSL,BKG,ASP,TPC,BMC,NO1,KMR,FCM,HTV,BRC,VTB,CMV,GMH,SHA,DTT,NAV,LM8,SPM,VCA,TCR,SVD,PIT,GTA,ST8,DTA,AAM,HAS,HU1,TDG,DXV"""

# 291 HNX tickers from stockanalysis.com
HNX_TICKERS = """KSF,KSV,PVS,NVB,PVI,HUT,IDC,MBS,SHS,THD,BAB,NTP,CEO,DTK,VCS,DHT,SCG,VIF,VNR,PTI,VC3,IPA,CDN,TNG,DNP,PGS,HHC,HGM,PRE,VFS,LAS,PLC,MVB,BVS,BCF,SLS,VTZ,SEB,LHC,PVC,NET,TIG,VGS,SZB,PMC,DP3,VIT,GMA,IDV,OCH,INN,L18,NFC,C69,DTD,MST,HLD,BCC,S99,WCS,CLM,EVS,TMB,TFC,PSD,HVT,VC7,VNC,IVS,DXP,NDN,TVC,HKT,L40,CAP,S55,L14,IDJ,SAF,BTS,TKU,SJE,PVB,CSC,PIC,HTC,NTH,HJS,DNC,SGC,BTW,VMS,VSM,NRC,TVD,PCT,SJ1,PCH,PHN,SHN,APS,VNF,BKC,DL1,VTV,TPP,API,VNT,PSI,AAV,NBC,AME,POT,SD9,GDW,VC2,EID,NBW,HLC,LIG,CTB,HMH,DVM,MBG,UNI,CCR,ICG,NAG,WSS,PPT,TV4,TTL,HOM,VHL,VSA,VCC,GLT,MAC,BAX,DST,PVG,VC6,CLH,SCI,MED,PMS,SGH,THT,MDC,KHS,KDM,SDU,NAP,PJC,VIG,X20,PCE,VGP,SD5,HCC,PDB,VC1,CIA,CMS,BNA,SED,TET,VBC,TDT,PPP,RCL,TTT,PPS,LDP,TV3,TA9,CAN,GMX,PTD,ARM,MAS,DTG,VDL,TOT,HBS,VMC,NST,PSW,PSE,TSB,GIC,QST,PMB,TJC,V12,KTS,KMT,LBE,MKV,DHP,MEL,EBS,THB,SHE,HAT,VCM,TMC,SDG,VHE,MIC,NBP,CAG,ATS,NSH,PIA,CTT,D11,TTH,PPY,SRA,ITQ,SPC,QTC,PV2,KST,DDG,MCF,SGD,STC,PSC,NHC,CKV,ONE,V21,DAD,DC2,ALT,ADC,CPC,BBS,VTH,MCC,PRC,PGN,SDN,DIH,VC9,STP,DS3,PBP,TTC,HAD,PGT,CTP,NDX,SMT,CET,FID,PMP,HMR,PTS,VTC,PEN,KSD,GKM,AMC,SDA,TMX,BPC,CMC,SFN,SMN,INC,PPE,VTJ,VLA,SVN,HEV,BXH,TXM,KKC,DAE,THS,CX8,SSM,HCT,MCO,VE1,SDC,VE3"""

def main():
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    hose = [t.strip() for t in HOSE_TICKERS.split(',') if t.strip()]
    hnx = [t.strip() for t in HNX_TICKERS.split(',') if t.strip()]
    all_tickers = sorted(set(hose + hnx))

    print(f"HOSE: {len(hose)}, HNX: {len(hnx)}, Total unique: {len(all_tickers)}")

    with conn.cursor() as cur:
        # 1. Seed ticker_universe
        rows = [(t, 'HOSE', f'{t}.VN', True, 'stockanalysis') for t in all_tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
        """, rows, page_size=200)
        print(f"Seeded {len(rows)} tickers into ticker_universe")

        # 2. Seed stock_directory with ticker as both symbol and name (names will be updated by fundamental_lite later)
        dir_rows = [(t, t, 'HOSE') for t in all_tickers]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange)
            VALUES %s
            ON CONFLICT (symbol, exchange) DO NOTHING
        """, dir_rows, page_size=200)
        print(f"Seeded {len(dir_rows)} rows into stock_directory")

        conn.commit()
    conn.close()
    print("Done!")

if __name__ == '__main__':
    main()
