#!/usr/bin/env python3

import argparse
import os
import json
import gzip
import csv
import tempfile
import sys
import time

MIN_ALIGNMENT_LENGTH = 15
NUMBER_OF_TOP_HITS_TO_KEEP = 10

PFAM_IDMAP_URL = 'ftp://ftp.ebi.ac.uk/pub/databases/Pfam/releases/Pfam31.0/database_files/pfamA.txt.gz'
PDB_IDMAP_URL = 'ftp://ftp.wwpdb.org/pub/pdb/derived_data/index/compound.idx'

TDM_SINGLE_FIELD_MAP = [('nice_name', 'label'), ('seq_count', 'seq_count'), ('structure_count', 'structure_count')]
TDM_MULTI_FIELD_MAP = [('ec_numbers', 'ec'), ('taxonomyids', 'tax'), ('gene_names', 'gene'), ('go_terms', 'go')]

parser = argparse.ArgumentParser(description='Merge annotations.')
parser.add_argument('dataset_file', metavar='DATASET_FILE', help='.genes.json.gz input file')
parser.add_argument('--3dm-dir', dest='tdm_dir', required=True)
parser.add_argument('--3dm-annotation', dest='tdm_annotation', required=True,
                    help='tab-separated file that has to be sorted by evalue (best hits first)')
parser.add_argument('--pfam-idmap', required=True, help='Download from: %s' % PFAM_IDMAP_URL)
# parser.add_argument('--pfam-annotation', required=True,
#                     help='tab-separated file that has to be sorted by evalue (best hits first)')
parser.add_argument('--pdb-idmap', required=True, help='Download from: %s' % PDB_IDMAP_URL)
parser.add_argument('--pdb-annotation', required=True,
                    help='tab-separated file that has to be sorted by evalue (best hits first)')
parser.add_argument('out_file', metavar='OUT_FILE', help='.genes.json.gz output file')
args = parser.parse_args()

tdm_map = {}
pfam_map = {}
pdb_map = {}

tdm_annotation_map = {}
pfam_annotation_map = {}
pdb_annotation_map = {}


def read_tdm_files():
  filelist = list(os.walk(args.tdm_dir))[0][2]
  print('Loading data from 3DM metadata files...')
  for filename in filelist:
    with open(os.path.join(args.tdm_dir, filename), 'rt') as file:
      # cat names | sed 's/_virusx_2016//' | sed 's/fam/f/'  | sed 's/sub/s/'
      tdm_id = filename.replace('.json', '').replace('_virusx_2016', '').replace('fam', 'f').replace('sub', 's')
      tdm_map[tdm_id] = json.load(file)[0]  # id => object
  print('Got %s entries after parsing %s files.' % (len(tdm_map), len(filelist)))
  print('Done.')


def read_pfam_idmap():
  print('Loading data from PFAM ID map file...')
  row_count = 0
  with gzip.open(args.pfam_idmap, 'rt', newline='') as file:
    pfam = csv.reader(file, delimiter='\t')
    for row in pfam:
      pfam_map[row[0].strip()] = (row[1].strip(), row[3].strip())  # id => (hmmname, description)
      row_count += 1
  print('Got %s entries after parsing %s rows.' % (len(pfam_map), row_count))
  print('Done.')


def read_pdb_idmap():
  print('Loading data from PDB ID map file...')
  row_count = 0
  with open(args.pdb_idmap, 'rt', newline='') as file:
    for _ in [1, 2, 3, 4]:  # skip header rows
      file.readline()
    pdb = csv.reader(file, delimiter='\t')
    for row in pdb:
      pdb_map[row[0].strip()] = row[1].strip()  # id => description
      row_count += 1
  print('Got %s entries after parsing %s rows.' % (len(pdb_map), row_count))
  print('Done.')


def gz_approximate_number_of_records(path):
  sample_amount = 1000
  with tempfile.SpooledTemporaryFile() as tmp:
    with gzip.open(tmp, 'wt') as tmpgz:
      gz_size = os.path.getsize(path)
      with gzip.open(path, 'rt') as file:
        for _ in range(0, sample_amount):
          tmpgz.write(file.readline())
        sample_size = file.tell()
    sample_gz_size = tmp.tell()
  return int(gz_size * (sample_size / sample_gz_size) * (sample_amount / sample_size))


def read_annotation(path, label, target_map):
  status_nth = (0b1 << 20) - 1
  stamp = time.time()
  print('Loading data from %s annotation file...' % label)
  approx_count = gz_approximate_number_of_records(path)
  print('Approx. number of records: %s' % approx_count)
  one_percent = int(approx_count / 100)
  with gzip.open(path, 'rt', newline='') as file:
    ann = csv.reader(file, delimiter='\t')
    row_count = 0
    for row in ann:
      row_count += 1
      if (row_count & status_nth) == status_nth:
        if time.time() > stamp + 5:
          print('%s%%' % int(row_count / one_percent), end=' ')
          stamp = time.time()
        sys.stdout.flush()
      geneid = row[0][10:]
      if not geneid in target_map:
        target_map[geneid] = []
      if int(row[3]) >= MIN_ALIGNMENT_LENGTH and len(target_map[geneid]) < NUMBER_OF_TOP_HITS_TO_KEEP:
        target_map[geneid].append({
          'id': row[1],
          'ident': float(row[2]),
          'alength': int(row[3]),
          'mismatch': int(row[4]),
          'gapopen': int(row[5]),
          'qstart': int(row[6]),
          'qend': int(row[7]),
          'sstart': int(row[8]),
          'send': int(row[9]),
          'evalue': float(row[10]),
          'bitscore': float(row[11])
        })
  print()
  print('Got %s entries after parsing %s rows.' % (len(target_map), row_count))


def extend_gene_annotation_pdb(gene):
  if gene['geneid'] in pdb_annotation_map:
    pdbs = pdb_annotation_map[gene['geneid']]
    for pdb in pdbs:
      try:
        pdb['label'] = pdb_map[pdb['id'][:4]]
      except KeyError:
        pass
    gene['x_pdb'] = pdbs


def extend_gene_annotation_tdm(gene):
  # 3DM
  # {
  #   "structure_count": 827,
  #   "superfamily": {
  #     "structure_count": 827,
  #     "cached_seq_clusters": 24229,
  #     "seq_count": 58943,
  #     "seq_clusters": 26854,
  #     "dbname": "nucleo_kinases_virusx_2016",
  #     "core_length": 223,
  #     "subfamily_count": 85,
  #     "nice_name": "Nucleotide kinases (2016)",
  #     "mutation_count": 6742,
  #     "proteins_with_gene_names": 57398,
  #     "ec_numbers": {
  #       "2.7.4.14": "0.894",
  #       "2.7.4.8": "12.570"
  #     },
  #     "taxonomyids": {
  #       "35525": "0.532",
  #       "9606": "0.331"
  #     },
  #     "proteins_with_ec_numbers": 1746,
  #     "proteins_with_taxonomy_ids": 73344,
  #     "gene_names": {
  #       "gmk": "16.997",
  #       "coaE": "14.499"
  #     },
  #     "go_terms": {
  #       "GO:0015937": "4.504",
  #       "GO:0008331": "2.632"
  #     },
  #     "proteins_with_go_terms": 487
  #   },
  #   "cached_seq_clusters": 24229,
  #   "seq_count": 58943,
  #   "seq_clusters": 26854,
  #   "dbname": "nucleo_kinases_virusx_2016",
  #   "core_length": 223,
  #   "subfamily_count": 85,
  #   "nice_name": "Nucleotide kinases (2016)",
  #   "mutation_count": 6742,
  #   "proteins_with_gene_names": 1004,
  #   "ec_numbers": {
  #     "2.7.4.8": "100.000"
  #   },
  #   "taxonomyids": {
  #     "1408": "0.480",
  #     "1280": "2.305"
  #   },
  #   "proteins_with_ec_numbers": 23,
  #   "proteins_with_taxonomy_ids": 1041,
  #   "gene_names": {
  #     "gmk": "97.908",
  #     "gmk46": "0.100"
  #   },
  #   "go_terms": {
  #     "GO:0005829": "50.000",
  #     "GO:0004385": "50.000"
  #   },
  #   "proteins_with_go_terms": 4
  # }
  if gene['geneid'] in tdm_annotation_map:
    tdms = tdm_annotation_map[gene['geneid']]
    for tdm in tdms:
      ref = tdm_map[tdm['id']]
      # single value fields
      for source_field, target_field in TDM_SINGLE_FIELD_MAP:
        tdm[target_field] = ref[source_field]
      # multi value maps
      for source_field, target_field in TDM_MULTI_FIELD_MAP:
        tdm[target_field] = []
        if ref[source_field]:
          for k, v in ref[source_field].items():
            tdm[target_field].append({'id': k, 'perc': float(v)})
        elif 'superfamily' in ref:
          for k, v in ref['superfamily'][source_field].items():
            tdm[target_field].append({'id': k, 'perc': float(v)})
    gene['x_3dm'] = tdms


def deduplicate_ecs(gene):
  gene['ecs'] = sorted(list(set(gene['ecs'])))


def extend_gene_annotation(gene):
  extend_gene_annotation_pdb(gene)
  extend_gene_annotation_tdm(gene)
  # TODO: pfam
  deduplicate_ecs(gene)
  return gene


def extend_dataset():
  status_nth = (0b1 << 14) - 1
  stamp = time.time()
  print('Extending dataset...')
  approx_count = gz_approximate_number_of_records(args.dataset_file)
  print('Approx. number of records: %s' % approx_count)
  one_percent = int(approx_count / 100)
  with gzip.open(args.dataset_file, 'rt') as file, gzip.open(args.out_file, 'wt') as out:
    is_header = True
    row_count = 0
    for line in file:
      row_count += 1
      if is_header:
        out.write(line)
      else:
        json.dump(extend_gene_annotation(json.loads(line)), out, separators=(',', ':'))
        out.write('\n')
      if (row_count & status_nth) == status_nth:
        if time.time() > stamp + 5:
          print('%s%%' % int(row_count / one_percent), end=' ')
          stamp = time.time()
        sys.stdout.flush()
      is_header = not is_header
  print()
  print('Done')
  print('Output: %s' % args.out_file)


if __name__ == '__main__':
  read_tdm_files()
  # read_pfam_idmap()
  read_pdb_idmap()
  read_annotation(args.tdm_annotation, '3DM', tdm_annotation_map)
  # read_annotation(args.pfam_annotation, 'Pfam', pfam_annotation_map)
  read_annotation(args.pdb_annotation, 'PDB', pdb_annotation_map)
  extend_dataset()
