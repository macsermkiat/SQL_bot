# Table Relationships (v2)

## Relationship Inference Logic

1. **Universal keys** (`hn`, `an`, `vn`) connect tables across all families
2. **Table families** are grouped by name prefix (e.g., RVST, RVSTDR, RVSTEXM)
3. **Domain-specific keys** (e.g., `reqno`, `labno`) only connect within their family

## Universal Keys

| Key | Description |
|-----|-------------|
| `hn` | Hospital Number - Patient identifier (universal) |
| `an` | Admission Number - Inpatient episode (universal) |
| `vn` | Visit Number - Outpatient visit (universal) |

## Domain-Specific Keys (family-scoped)

| Key | Description |
|-----|-------------|
| `reqno` | Request number (domain-specific) |
| `labno` | Lab order number (lab tables only) |
| `rxno` | Prescription number (pharmacy tables only) |
| `ancno` | ANC number (antenatal tables only) |
| `invno` | Invoice number (billing tables only) |
| `docno` | Document number (document tables only) |

## Table Families (110 families)

### MED (11 tables)

- MEDFORM
- MEDGENERIC
- MEDLBLHLP
- MEDSALEHST
- MEDSYMPTOM
- MEDTYPE
- MEDUNIT
- MEDUSEQTY
- MEDUSETIME
- MEDUSETYPE
- MEDUSEUNIT

### BDVST (6 tables)

- BDVST
- BDVSTCSMT
- BDVSTDT
- BDVSTST
- BDVSTTRANS
- BDVST_ABO

### DLVST (5 tables)

- DLVST
- DLVSTAFBRTHSIGN
- DLVSTDESC
- DLVSTDT
- DLVSTEXT

### EYESCREEN (5 tables)

- EYESCREEN
- EYESCREENDIAG
- EYESCREENEXAM
- EYESCREENNURSE
- EYESCREENOPTOMETRY

### IPT (5 tables)

- IPT
- IPTINFANTMOTHER
- IPTSUMDCT
- IPTSUMDIAG
- IPTSUMOPRT

### LAB (5 tables)

- LABMEDICINE
- LABORGANISM_ITA
- LABORGANQTY_ITA
- LABORTYPE
- LABSPCM

### OVST (5 tables)

- OVST
- OVSTDISCHANGE
- OVSTIST
- OVSTOST
- OVSTPRESS

### PRSC (5 tables)

- PRSC
- PRSCDORD
- PRSCDT
- PRSCDTEXT
- PRSCTYPEPT

### PT (5 tables)

- PT
- PTDIAG
- PTICD9CM
- PTOPRT
- PTPHYSICALEXAM

### RM (5 tables)

- RM
- RMLCT
- RMLCTTYPE
- RMTYPE
- RMTYPEGRP

### BD (4 tables)

- BDBRANCH
- BDLABANC
- BDTYPE
- BDUSETYPE

### CN (3 tables)

- CNER
- CNERCAUSE
- CNERPLACE

### DCTORDER (3 tables)

- DCTORDER
- DCTORDERPATHOPREG
- DCTORDERPRSC

### IPTADM (3 tables)

- IPTADM
- IPTADMIST
- IPTADMOST

### IPTBOOK (3 tables)

- IPTBOOKBEDICU
- IPTBOOKBEDICU2
- IPTBOOKBEDICUHST

### LABEXM (3 tables)

- LABEXM
- LABEXMSPCM
- LABEXM_CAT

### LVSTEXM (3 tables)

- LVSTEXM
- LVSTEXMBAC1
- LVSTEXMBAC2

### MAST (3 tables)

- MASTERORDER
- MASTERSALE
- MASTERSALEPTTYPE

### MEDITEM (3 tables)

- MEDITEMDIS
- MEDITEMGNR
- MEDITEMPHM

### OPDDCT (3 tables)

- OPDDCTORDER
- OPDDCTPRSC
- OPDDCTRDO

### PTTYPE (3 tables)

- PTTYPE
- PTTYPEEXT
- PTTYPEGRP

### WARD (3 tables)

- WARD
- WARDICU
- WARDROOMHST

### ARPT (2 tables)

- ARPT
- ARPTINC

### CMIA (2 tables)

- CMIATEST
- CMIATESTNEW

### DCT (2 tables)

- DCT
- DCTDISCHANGE

### ERDC (2 tables)

- ERDCHST
- ERDCHSTTYPE

### LPTV (2 tables)

- LPTVST
- LPTVSTEXM

### MOL (2 tables)

- MOLGT
- MOLGTDT

### MOTP (2 tables)

- MOTP
- MOTPDT

### OPDLED (2 tables)

- OPDLEDCALL
- OPDLEDDCTPT

### OPPOST (2 tables)

- OPPOSTOPDIAG
- OPPOSTOPERATION

### OPPROC (2 tables)

- OPPROCEDURE
- OPPROCEDUREDCT

### OPRT (2 tables)

- OPRTACT
- OPRTACTICD9CM

### ANCHISTORY (1 tables)

- ANCHISTORY

### ANC (1 tables)

- ANCNO

### ANCPLACE (1 tables)

- ANCPLACE

### ANCVST (1 tables)

- ANCVST

### ANPR (1 tables)

- ANPREOP

### BDUNIT (1 tables)

- BDUNITSTAT

### BLOO (1 tables)

- BLOODTEST

### BOOK (1 tables)

- BOOKST

### CANC (1 tables)

- CANCELCS

### CHAN (1 tables)

- CHANGWAT

### CLAIMLCT (1 tables)

- CLAIMLCT

### CLAIMTITLE (1 tables)

- CLAIMTITLE

### CLINICLCT (1 tables)

- CLINICLCT

### CLINICTYPE (1 tables)

- CLINICTYPE

### DCHS (1 tables)

- DCHST

### DCHT (1 tables)

- DCHTYPE

### DIAG (1 tables)

- DIAGTYPE

### DLAN (1 tables)

- DLANORMAL

### DLMED (1 tables)

- DLMEDICATION

### DL (1 tables)

- DLPLCNTTYPE

### DLPOS (1 tables)

- DLPOSITION

### DLRUP (1 tables)

- DLRUPTURETYPE

### EMRG (1 tables)

- EMRGNCY

### ERIL (1 tables)

- ERILLNESS

### ERZO (1 tables)

- ERZONELCT

### EYEASSESS (1 tables)

- EYEASSESSMENT

### HIVT (1 tables)

- HIVTEST

### HRPO (1 tables)

- HRPOSITION

### ICD1 (1 tables)

- ICD10

### ICD9 (1 tables)

- ICD9CM

### INCG (1 tables)

- INCGRP

### INCPRVLG (1 tables)

- INCPRVLG

### INCPT (1 tables)

- INCPT

### IPTSUMM (1 tables)

- IPTSUMMARY

### ISPM (1 tables)

- ISPMCREC

### ISPT (1 tables)

- ISPTYPE

### ISPU (1 tables)

- ISPUSEMC

### LABGRP (1 tables)

- LABGRP

### LCT (1 tables)

- LCT

### LCTT (1 tables)

- LCTTYPE

### LPTE (1 tables)

- LPTEXM

### LVST (1 tables)

- LVST

### MAIN (1 tables)

- MAINHPT

### MALE (1 tables)

- MALE

### MEDACC (1 tables)

- MEDACCNATION

### MEDCTRL (1 tables)

- MEDCTRLTYPE

### MEDCURE (1 tables)

- MEDCURE

### MEDDORD (1 tables)

- MEDDORDTYPE

### NTNL (1 tables)

- NTNLTY

### OAPP (1 tables)

- OAPP

### OCCP (1 tables)

- OCCPTN

### OPIN (1 tables)

- OPINTRAOP

### OPREQ (1 tables)

- OPREQVST

### OPVS (1 tables)

- OPVST

### ORGA (1 tables)

- ORGANISM

### ORRO (1 tables)

- ORROOM

### PAID (1 tables)

- PAIDST

### PTALLERGY (1 tables)

- PTALLERGY

### RAPP (1 tables)

- RAPP

### RDOEXM (1 tables)

- RDOEXM

### RDO (1 tables)

- RDOGRP

### REQS (1 tables)

- REQST

### RHTE (1 tables)

- RHTEST

### RMDT (1 tables)

- RMDT

### RVST (1 tables)

- RVST

### RVSTDR (1 tables)

- RVSTDR

### RVSTEXM (1 tables)

- RVSTEXM

### RVSTST (1 tables)

- RVSTST

### SPCL (1 tables)

- SPCLTY

### SSHP (1 tables)

- SSHPT

### STRE (1 tables)

- STRENGTHUNIT

### TPHA (1 tables)

- TPHATEST

### TREA (1 tables)

- TREATLINE

### TRNS (1 tables)

- TRNSPORT

### UNIT (1 tables)

- UNIT

### VOLU (1 tables)

- VOLUMEUNIT

### WSKI (1 tables)

- WSKIOSKVISITID

## Inferred Relationships (459 total)

### High Confidence (universal keys)

| From | Column | To | Key Type |
|------|--------|-----|----------|
| ANCVST | cliniclct | CLINICLCT | table match |
| ANCVST | an | IPT | universal |
| ANCVST | vn | IPT | universal |
| ANCVST | occptn | OCCPTN | table match |
| ANCVST | hn | PT | universal |
| ANCVST | treatline | TREATLINE | table match |
| ANPREOP | an | IPT | universal |
| ANPREOP | hn | PT | universal |
| ARPT | changwat | CHANGWAT | table match |
| ARPT | claimlct | CLAIMLCT | table match |
| ARPT | dchst | DCHST | table match |
| ARPT | dchtype | DCHTYPE | table match |
| ARPT | an | IPT | universal |
| ARPT | mainhpt | MAINHPT | table match |
| ARPT | hn | PT | universal |
| ARPT | pttype | PTTYPE | table match |
| ARPT | pttypeext | PTTYPEEXT | table match |
| ARPTINC | incgrp | INCGRP | table match |
| BDLABANC | hn | PT | universal |
| BDVST | bdbranch | BDBRANCH | table match |
| BDVST | bdvstst | BDVSTST | table match |
| BDVST | cancelcs | CANCELCS | table match |
| BDVST | dct | DCT | table match |
| BDVST | icd10 | ICD10 | table match |
| BDVST | an | IPT | universal |
| BDVST | vn | IPT | universal |
| BDVST | hn | PT | universal |
| BDVST | pttype | PTTYPE | table match |
| BDVSTCSMT | bdtype | BDTYPE | table match |
| BDVSTCSMT | hn | PT | universal |
| BDVSTDT | bdtype | BDTYPE | table match |
| BDVSTDT | hn | PT | universal |
| BDVSTTRANS | bdtype | BDTYPE | table match |
| BDVSTTRANS | an | IPT | universal |
| BDVSTTRANS | vn | IPT | universal |
| BDVSTTRANS | hn | PT | universal |
| BDVST_ABO | dct | DCT | table match |
| BDVST_ABO | hn | PT | universal |
| CLAIMLCT | changwat | CHANGWAT | table match |
| CLAIMLCT | claimtitle | CLAIMTITLE | table match |
| CLINICLCT | clinictype | CLINICTYPE | table match |
| CLINICLCT | dct | DCT | table match |
| CLINICLCT | spclty | SPCLTY | table match |
| CNER | changwat | CHANGWAT | table match |
| CNER | cliniclct | CLINICLCT | table match |
| CNER | cnercause | CNERCAUSE | table match |
| CNER | cnerplace | CNERPLACE | table match |
| CNER | erdchst | ERDCHST | table match |
| CNER | erdchsttype | ERDCHSTTYPE | table match |
| CNER | erillness | ERILLNESS | table match |
| CNER | hn | PT | universal |
| DCT | spclty | SPCLTY | table match |
| DCT | treatline | TREATLINE | table match |
| DCTDISCHANGE | ovstost | OVSTOST | table match |
| DCTORDER | an | IPT | universal |
| DCTORDER | hn | PT | universal |
| DCTORDERPATHOPREG | hn | PT | universal |
| DCTORDERPRSC | an | IPT | universal |
| DCTORDERPRSC | medsymptom | MEDSYMPTOM | table match |
| DCTORDERPRSC | meduseqty | MEDUSEQTY | table match |
| DCTORDERPRSC | medusetime | MEDUSETIME | table match |
| DCTORDERPRSC | medusetype | MEDUSETYPE | table match |
| DCTORDERPRSC | meduseunit | MEDUSEUNIT | table match |
| DCTORDERPRSC | hn | PT | universal |
| DLVST | ancplace | ANCPLACE | table match |
| DLVST | cmiatest | CMIATEST | table match |
| DLVST | cmiatestnew | CMIATESTNEW | table match |
| DLVST | hivtest | HIVTEST | table match |
| DLVST | icd10 | ICD10 | table match |
| DLVST | rhtest | RHTEST | table match |
| DLVST | tphatest | TPHATEST | table match |
| DLVSTAFBRTHSIGN | icd10 | ICD10 | table match |
| DLVSTDESC | dlposition | DLPOSITION | table match |
| DLVSTDT | dlanormal | DLANORMAL | table match |
| DLVSTDT | male | MALE | table match |
| DLVSTDT | ntnlty | NTNLTY | table match |
| DLVSTEXT | ancplace | ANCPLACE | table match |
| DLVSTEXT | changwat | CHANGWAT | table match |
| DLVSTEXT | cmiatest | CMIATEST | table match |
| DLVSTEXT | cmiatestnew | CMIATESTNEW | table match |
| DLVSTEXT | hivtest | HIVTEST | table match |
| DLVSTEXT | an | IPT | universal |
| DLVSTEXT | hn | PT | universal |
| DLVSTEXT | rhtest | RHTEST | table match |
| DLVSTEXT | tphatest | TPHATEST | table match |
| DLVSTEXT | ward | WARD | table match |
| ERDCHSTTYPE | erdchst | ERDCHST | table match |
| ERZONELCT | cliniclct | CLINICLCT | table match |
| EYEASSESSMENT | cliniclct | CLINICLCT | table match |
| EYEASSESSMENT | hn | PT | universal |
| EYESCREEN | cliniclct | CLINICLCT | table match |
| EYESCREEN | dct | DCT | table match |
| EYESCREEN | hn | PT | universal |
| EYESCREENDIAG | cliniclct | CLINICLCT | table match |
| EYESCREENDIAG | hn | PT | universal |
| EYESCREENEXAM | cliniclct | CLINICLCT | table match |
| EYESCREENEXAM | hn | PT | universal |
| EYESCREENNURSE | cliniclct | CLINICLCT | table match |
| EYESCREENNURSE | hn | PT | universal |
| EYESCREENOPTOMETRY | cliniclct | CLINICLCT | table match |
| EYESCREENOPTOMETRY | hn | PT | universal |
| ICD10 | male | MALE | table match |
| ICD9CM | male | MALE | table match |
| INCPRVLG | changwat | CHANGWAT | table match |
| INCPRVLG | claimlct | CLAIMLCT | table match |
| INCPRVLG | an | IPT | universal |
| INCPRVLG | mainhpt | MAINHPT | table match |
| INCPRVLG | hn | PT | universal |
| INCPRVLG | pttype | PTTYPE | table match |
| INCPRVLG | pttypeext | PTTYPEEXT | table match |
| INCPRVLG | sshpt | SSHPT | table match |
| INCPT | dct | DCT | table match |
| INCPT | incgrp | INCGRP | table match |
| INCPT | an | IPT | universal |
| INCPT | vn | IPT | universal |
| INCPT | paidst | PAIDST | table match |
| INCPT | hn | PT | universal |
| INCPT | pttype | PTTYPE | table match |
| INCPT | pttypeext | PTTYPEEXT | table match |
| INCPT | ward | WARD | table match |
| IPT | cancelcs | CANCELCS | table match |
| IPT | claimlct | CLAIMLCT | table match |
| IPT | dchst | DCHST | table match |
| IPT | dchtype | DCHTYPE | table match |
| IPT | dct | DCT | table match |
| IPT | hn | PT | universal |
| IPT | spclty | SPCLTY | table match |
| IPT | treatline | TREATLINE | table match |
| IPT | ward | WARD | table match |
| IPTADM | dct | DCT | table match |
| IPTADM | an | IPT | universal |
| IPTADM | iptadmist | IPTADMIST | table match |
| IPTADM | iptadmost | IPTADMOST | table match |
| IPTADM | pttype | PTTYPE | table match |
| IPTADM | spclty | SPCLTY | table match |
| IPTADM | treatline | TREATLINE | table match |
| IPTADM | ward | WARD | table match |
| IPTBOOKBEDICU | cliniclct | CLINICLCT | table match |
| IPTBOOKBEDICU | dct | DCT | table match |
| IPTBOOKBEDICU | an | IPT | universal |
| IPTBOOKBEDICU | hn | PT | universal |
| IPTBOOKBEDICU | treatline | TREATLINE | table match |
| IPTBOOKBEDICU | ward | WARD | table match |
| IPTBOOKBEDICU2 | hn | PT | universal |
| IPTBOOKBEDICUHST | hn | PT | universal |
| IPTINFANTMOTHER | an | IPT | universal |
| IPTINFANTMOTHER | hn | PT | universal |
| IPTSUMDCT | dchst | DCHST | table match |
| IPTSUMDCT | dchtype | DCHTYPE | table match |
| IPTSUMDCT | an | IPT | universal |
| IPTSUMDCT | labortype | LABORTYPE | table match |
| IPTSUMDCT | male | MALE | table match |
| IPTSUMDCT | hn | PT | universal |
| IPTSUMDCT | spclty | SPCLTY | table match |
| IPTSUMDCT | tphatest | TPHATEST | table match |
| IPTSUMDCT | ward | WARD | table match |
| IPTSUMDIAG | diagtype | DIAGTYPE | table match |
| IPTSUMDIAG | icd10 | ICD10 | table match |
| IPTSUMDIAG | an | IPT | universal |
| IPTSUMDIAG | spclty | SPCLTY | table match |
| IPTSUMMARY | changwat | CHANGWAT | table match |
| IPTSUMMARY | dchst | DCHST | table match |
| IPTSUMMARY | dchtype | DCHTYPE | table match |
| IPTSUMMARY | an | IPT | universal |
| IPTSUMMARY | labortype | LABORTYPE | table match |
| IPTSUMMARY | male | MALE | table match |
| IPTSUMMARY | ntnlty | NTNLTY | table match |
| IPTSUMMARY | occptn | OCCPTN | table match |
| IPTSUMMARY | hn | PT | universal |
| IPTSUMMARY | spclty | SPCLTY | table match |
| IPTSUMMARY | tphatest | TPHATEST | table match |
| IPTSUMMARY | ward | WARD | table match |
| IPTSUMOPRT | icd9cm | ICD9CM | table match |
| IPTSUMOPRT | an | IPT | universal |
| ISPMCREC | isptype | ISPTYPE | table match |
| ISPUSEMC | cliniclct | CLINICLCT | table match |
| ISPUSEMC | an | IPT | universal |
| ISPUSEMC | isptype | ISPTYPE | table match |
| ISPUSEMC | hn | PT | universal |
| ISPUSEMC | pttype | PTTYPE | table match |
| ISPUSEMC | pttypeext | PTTYPEEXT | table match |
| LABEXM | cancelcs | CANCELCS | table match |
| LABEXM | emrgncy | EMRGNCY | table match |
| LABEXM | labgrp | LABGRP | table match |
| LABEXM | labspcm | LABSPCM | table match |
| LABEXMSPCM | labexm | LABEXM | table match |
| LABEXMSPCM | labgrp | LABGRP | table match |
| LABEXMSPCM | labspcm | LABSPCM | table match |
| LABEXM_CAT | labexm | LABEXM | table match |
| LABEXM_CAT | labgrp | LABGRP | table match |
| LABMEDICINE | unit | UNIT | table match |
| LABORGANISM_ITA | organism | ORGANISM | table match |
| LABSPCM | labgrp | LABGRP | table match |
| LCT | lcttype | LCTTYPE | table match |
| LCT | rmlct | RMLCT | table match |
| LPTEXM | cancelcs | CANCELCS | table match |
| LPTVST | cancelcs | CANCELCS | table match |
| LPTVST | dct | DCT | table match |
| LPTVST | an | IPT | universal |
| LPTVST | vn | IPT | universal |
| LPTVST | hn | PT | universal |
| LPTVSTEXM | cancelcs | CANCELCS | table match |
| LPTVSTEXM | an | IPT | universal |
| LPTVSTEXM | lptexm | LPTEXM | table match |
| LPTVSTEXM | hn | PT | universal |
| LVST | cancelcs | CANCELCS | table match |
| LVST | dct | DCT | table match |
| LVST | an | IPT | universal |
| LVST | vn | IPT | universal |
| LVST | labgrp | LABGRP | table match |
| LVST | hn | PT | universal |
| LVSTEXM | emrgncy | EMRGNCY | table match |
| LVSTEXM | an | IPT | universal |
| LVSTEXM | labexm | LABEXM | table match |
| LVSTEXM | labgrp | LABGRP | table match |
| LVSTEXM | labspcm | LABSPCM | table match |
| LVSTEXM | hn | PT | universal |
| LVSTEXMBAC1 | labexm | LABEXM | table match |
| LVSTEXMBAC1 | labgrp | LABGRP | table match |
| LVSTEXMBAC1 | organism | ORGANISM | table match |
| LVSTEXMBAC2 | labexm | LABEXM | table match |
| LVSTEXMBAC2 | labgrp | LABGRP | table match |
| MAINHPT | changwat | CHANGWAT | table match |
| MASTERORDER | dct | DCT | table match |
| MASTERORDER | incgrp | INCGRP | table match |
| MASTERORDER | lct | LCT | table match |
| MASTERSALEPTTYPE | pttype | PTTYPE | table match |
| MASTERSALEPTTYPE | pttypegrp | PTTYPEGRP | table match |
| MEDITEMDIS | male | MALE | table match |
| MEDITEMDIS | medaccnation | MEDACCNATION | table match |
| MEDITEMDIS | medctrltype | MEDCTRLTYPE | table match |
| MEDITEMDIS | medcure | MEDCURE | table match |
| MEDITEMDIS | medform | MEDFORM | table match |
| MEDITEMDIS | medsymptom | MEDSYMPTOM | table match |
| MEDITEMDIS | medtype | MEDTYPE | table match |
| MEDITEMDIS | meduseqty | MEDUSEQTY | table match |
| MEDITEMDIS | medusetime | MEDUSETIME | table match |
| MEDITEMDIS | medusetype | MEDUSETYPE | table match |
| MEDITEMDIS | meduseunit | MEDUSEUNIT | table match |
| MEDITEMDIS | strengthunit | STRENGTHUNIT | table match |
| MEDITEMDIS | volumeunit | VOLUMEUNIT | table match |
| MEDITEMGNR | strengthunit | STRENGTHUNIT | table match |
| MEDUNIT | volumeunit | VOLUMEUNIT | table match |
| MEDUSETYPE | medform | MEDFORM | table match |
| MEDUSEUNIT | volumeunit | VOLUMEUNIT | table match |
| MOLGT | cancelcs | CANCELCS | table match |
| MOLGT | ward | WARD | table match |
| MOLGTDT | an | IPT | universal |
| MOLGTDT | hn | PT | universal |
| MOTPDT | medunit | MEDUNIT | table match |
| OAPP | cancelcs | CANCELCS | table match |
| OAPP | dct | DCT | table match |
| OAPP | an | IPT | universal |
| OAPP | labgrp | LABGRP | table match |
| OAPP | hn | PT | universal |
| OAPP | treatline | TREATLINE | table match |
| OAPP | ward | WARD | table match |
| OPDDCTORDER | cliniclct | CLINICLCT | table match |
| OPDDCTORDER | dct | DCT | table match |
| OPDDCTORDER | an | IPT | universal |
| OPDDCTORDER | hn | PT | universal |
| OPDDCTORDER | pttype | PTTYPE | table match |
| OPDDCTORDER | pttypeext | PTTYPEEXT | table match |
| OPDDCTPRSC | medsymptom | MEDSYMPTOM | table match |
| OPDDCTPRSC | meduseqty | MEDUSEQTY | table match |
| OPDDCTPRSC | medusetime | MEDUSETIME | table match |
| OPDDCTPRSC | medusetype | MEDUSETYPE | table match |
| OPDDCTPRSC | meduseunit | MEDUSEUNIT | table match |
| OPDDCTPRSC | hn | PT | universal |
| OPDDCTRDO | cliniclct | CLINICLCT | table match |
| OPDDCTRDO | an | IPT | universal |
| OPDDCTRDO | hn | PT | universal |
| OPDDCTRDO | rdoexm | RDOEXM | table match |
| OPDDCTRDO | rdogrp | RDOGRP | table match |
| OPDLEDCALL | cliniclct | CLINICLCT | table match |
| OPDLEDCALL | dct | DCT | table match |
| OPDLEDCALL | hn | PT | universal |
| OPDLEDDCTPT | cliniclct | CLINICLCT | table match |
| OPDLEDDCTPT | dct | DCT | table match |
| OPDLEDDCTPT | hn | PT | universal |
| OPINTRAOP | an | IPT | universal |
| OPINTRAOP | hn | PT | universal |
| OPPOSTOPDIAG | an | IPT | universal |
| OPPOSTOPDIAG | hn | PT | universal |
| OPPOSTOPERATION | an | IPT | universal |
| OPPOSTOPERATION | hn | PT | universal |
| OPPROCEDURE | hn | PT | universal |
| OPPROCEDUREDCT | hn | PT | universal |
| OPREQVST | cliniclct | CLINICLCT | table match |
| OPREQVST | an | IPT | universal |
| OPREQVST | vn | IPT | universal |
| OPREQVST | orroom | ORROOM | table match |
| OPREQVST | hn | PT | universal |
| OPREQVST | reqst | REQST | table match |
| OPREQVST | treatline | TREATLINE | table match |
| OPREQVST | ward | WARD | table match |
| OPRTACT | icd9cm | ICD9CM | table match |
| OPRTACT | spclty | SPCLTY | table match |
| OPRTACT | unit | UNIT | table match |
| OPRTACTICD9CM | icd9cm | ICD9CM | table match |
| OPRTACTICD9CM | oprtact | OPRTACT | table match |
| OPVST | an | IPT | universal |
| OPVST | vn | IPT | universal |
| OPVST | hn | PT | universal |
| OVST | cliniclct | CLINICLCT | table match |
| OVST | dct | DCT | table match |
| OVST | emrgncy | EMRGNCY | table match |
| OVST | an | IPT | universal |
| OVST | vn | IPT | universal |
| OVST | ovstist | OVSTIST | table match |
| OVST | ovstost | OVSTOST | table match |
| OVST | hn | PT | universal |
| OVST | spclty | SPCLTY | table match |
| OVST | treatline | TREATLINE | table match |
| OVST | trnsport | TRNSPORT | table match |
| OVSTDISCHANGE | cliniclct | CLINICLCT | table match |
| OVSTDISCHANGE | dctdischange | DCTDISCHANGE | table match |
| OVSTDISCHANGE | hn | PT | universal |
| OVSTPRESS | cliniclct | CLINICLCT | table match |
| OVSTPRESS | emrgncy | EMRGNCY | table match |
| OVSTPRESS | an | IPT | universal |
| OVSTPRESS | vn | IPT | universal |
| OVSTPRESS | hn | PT | universal |
| PRSC | an | IPT | universal |
| PRSC | vn | IPT | universal |
| PRSC | prsctypept | PRSCTYPEPT | table match |
| PRSC | hn | PT | universal |
| PRSC | pttype | PTTYPE | table match |
| PRSC | pttypeext | PTTYPEEXT | table match |
| PRSCDORD | an | IPT | universal |
| PRSCDORD | meddordtype | MEDDORDTYPE | table match |
| PRSCDORD | medsymptom | MEDSYMPTOM | table match |
| PRSCDORD | meduseqty | MEDUSEQTY | table match |
| PRSCDORD | medusetime | MEDUSETIME | table match |
| PRSCDORD | medusetype | MEDUSETYPE | table match |
| PRSCDORD | meduseunit | MEDUSEUNIT | table match |
| PRSCDT | meddordtype | MEDDORDTYPE | table match |
| PRSCDT | medsymptom | MEDSYMPTOM | table match |
| PRSCDT | meduseqty | MEDUSEQTY | table match |
| PRSCDT | medusetime | MEDUSETIME | table match |
| PRSCDT | medusetype | MEDUSETYPE | table match |
| PRSCDT | meduseunit | MEDUSEUNIT | table match |
| PRSCDT | pttype | PTTYPE | table match |
| PRSCDT | pttypeext | PTTYPEEXT | table match |
| PT | cancelcs | CANCELCS | table match |
| PT | male | MALE | table match |
| PT | ntnlty | NTNLTY | table match |
| PTALLERGY | cancelcs | CANCELCS | table match |
| PTALLERGY | icd10 | ICD10 | table match |
| PTALLERGY | an | IPT | universal |
| PTALLERGY | hn | PT | universal |
| PTALLERGY | ward | WARD | table match |
| PTDIAG | cliniclct | CLINICLCT | table match |
| PTDIAG | diagtype | DIAGTYPE | table match |
| PTDIAG | icd10 | ICD10 | table match |
| PTDIAG | an | IPT | universal |
| PTDIAG | vn | IPT | universal |
| PTDIAG | hn | PT | universal |
| PTDIAG | spclty | SPCLTY | table match |
| PTICD9CM | cliniclct | CLINICLCT | table match |
| PTICD9CM | icd9cm | ICD9CM | table match |
| PTICD9CM | an | IPT | universal |
| PTICD9CM | vn | IPT | universal |
| PTICD9CM | hn | PT | universal |
| PTOPRT | dct | DCT | table match |
| PTOPRT | icd9cm | ICD9CM | table match |
| PTOPRT | an | IPT | universal |
| PTOPRT | vn | IPT | universal |
| PTOPRT | oprtact | OPRTACT | table match |
| PTOPRT | hn | PT | universal |
| PTOPRT | pttype | PTTYPE | table match |
| PTPHYSICALEXAM | cliniclct | CLINICLCT | table match |
| PTPHYSICALEXAM | dct | DCT | table match |
| PTPHYSICALEXAM | hn | PT | universal |
| PTTYPE | pttypegrp | PTTYPEGRP | table match |
| PTTYPEEXT | claimlct | CLAIMLCT | table match |
| PTTYPEEXT | pttype | PTTYPE | table match |
| PTTYPEEXT | sshpt | SSHPT | table match |
| RAPP | cancelcs | CANCELCS | table match |
| RAPP | dct | DCT | table match |
| RAPP | an | IPT | universal |
| RAPP | hn | PT | universal |
| RAPP | rdogrp | RDOGRP | table match |
| RDOEXM | cancelcs | CANCELCS | table match |
| RDOEXM | rdogrp | RDOGRP | table match |
| RDOGRP | cancelcs | CANCELCS | table match |
| RM | changwat | CHANGWAT | table match |
| RM | rmlct | RMLCT | table match |
| RMDT | rmtype | RMTYPE | table match |
| RMLCT | rmlcttype | RMLCTTYPE | table match |
| RMTYPE | rmtypegrp | RMTYPEGRP | table match |
| RVST | cancelcs | CANCELCS | table match |
| RVST | dct | DCT | table match |
| RVST | an | IPT | universal |
| RVST | vn | IPT | universal |
| RVST | hn | PT | universal |
| RVST | pttype | PTTYPE | table match |
| RVST | pttypeext | PTTYPEEXT | table match |
| RVST | rdogrp | RDOGRP | table match |
| RVST | rvstst | RVSTST | table match |
| RVSTDR | dct | DCT | table match |
| RVSTDR | an | IPT | universal |
| RVSTDR | vn | IPT | universal |
| RVSTDR | hn | PT | universal |
| RVSTDR | pttype | PTTYPE | table match |
| RVSTDR | rdoexm | RDOEXM | table match |
| RVSTDR | rdogrp | RDOGRP | table match |
| RVSTEXM | emrgncy | EMRGNCY | table match |
| RVSTEXM | hn | PT | universal |
| RVSTEXM | pttype | PTTYPE | table match |
| RVSTEXM | pttypeext | PTTYPEEXT | table match |
| RVSTEXM | rdoexm | RDOEXM | table match |
| RVSTEXM | rdogrp | RDOGRP | table match |
| SSHPT | changwat | CHANGWAT | table match |
| WARDICU | ward | WARD | table match |
| WARDROOMHST | dct | DCT | table match |
| WARDROOMHST | an | IPT | universal |
| WARDROOMHST | treatline | TREATLINE | table match |
| WARDROOMHST | ward | WARD | table match |
| WSKIOSKVISITID | cliniclct | CLINICLCT | table match |
| WSKIOSKVISITID | dct | DCT | table match |
| WSKIOSKVISITID | hn | PT | universal |
| WSKIOSKVISITID | trnsport | TRNSPORT | table match |

### Medium Confidence (within-family)

| From | Column | To | Family |
|------|--------|-----|--------|
| ARPTINC | arno | ARPT | ARPT |
| BDVSTCSMT | hn | BDVST | BDVST |
| BDVSTDT | reqno | BDVST | BDVST |
| BDVSTTRANS | hn | BDVST | BDVST |
| BDVST_ABO | hn | BDVST | BDVST |
| DCTORDERPATHOPREG | hn | DCTORDER | DCTORDER |
| DCTORDERPRSC | hn | DCTORDER | DCTORDER |
| DLVSTAFBRTHSIGN | dlvstreqno | DLVST | DLVST |
| DLVSTDESC | dlvstreqno | DLVST | DLVST |
| DLVSTDT | dlvstreqno | DLVST | DLVST |
| DLVSTEXT | dlvstreqno | DLVST | DLVST |
| EYESCREENDIAG | hn | EYESCREEN | EYESCREEN |
| EYESCREENEXAM | hn | EYESCREEN | EYESCREEN |
| EYESCREENNURSE | hn | EYESCREEN | EYESCREEN |
| EYESCREENOPTOMETRY | hn | EYESCREEN | EYESCREEN |
| IPTBOOKBEDICU2 | hn | IPTBOOKBEDICU | IPTBOOK |
| IPTBOOKBEDICUHST | hn | IPTBOOKBEDICU | IPTBOOK |
| IPTINFANTMOTHER | hn | IPT | IPT |
| IPTSUMDCT | hn | IPT | IPT |
| LPTVSTEXM | hn | LPTVST | LPTV |
| LVSTEXMBAC1 | labno | LVSTEXM | LVSTEXM |
| LVSTEXMBAC2 | labno | LVSTEXM | LVSTEXM |
| MASTERORDER | ordercode | MASTERSALE | MAST |
| MASTERSALEPTTYPE | ordercode | MASTERSALE | MAST |
| MOLGTDT | molgtno | MOLGT | MOL |
| MOTPDT | motpno | MOTP | MOTP |
| OPDDCTORDER | hn | OPDDCTRDO | OPDDCT |
| OPDDCTPRSC | hn | OPDDCTRDO | OPDDCT |
| OPDLEDDCTPT | hn | OPDLEDCALL | OPDLED |
| OPPOSTOPERATION | hn | OPPOSTOPDIAG | OPPOST |
| OPPROCEDUREDCT | hn | OPPROCEDURE | OPPROC |
| OVSTDISCHANGE | hn | OVST | OVST |
| OVSTPRESS | hn | OVST | OVST |
| PRSCDORD | prscno | PRSC | PRSC |
| PRSCDT | prvno | PRSC | PRSC |
| PRSCDTEXT | prscno | PRSC | PRSC |
