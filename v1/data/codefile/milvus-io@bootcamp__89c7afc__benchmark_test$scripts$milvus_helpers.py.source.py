import sys
from pymilvus_orm import connections, Index
from pymilvus_orm.types import DataType
from pymilvus_orm.schema import FieldSchema, CollectionSchema
from pymilvus_orm.collection import Collection
from config import MILVUS_HOST, MILVUS_PORT, VECTOR_DIMENSION, METRIC_TYPE, NLIST
from pymilvus_orm import utility
from logs import LOGGER


class MilvusHelper:
    def __init__(self):
        try:
            self.collection = None
            connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
            LOGGER.debug("Successfully connect to Milvus with IP:{} and PORT:{}".format(MILVUS_HOST, MILVUS_PORT))
        except Exception as e:
            LOGGER.error("Failed to connect Milvus: {}".format(e))
            sys.exit(1)

    def set_collection(self, collection_name):
        try:
            if self.has_collection(collection_name):
                self.collection = Collection(name=collection_name)
            else:
                raise Exception("There has no collection named:{}".format(collection_name))
        except Exception as e:
            LOGGER.error("Failed to set collection: {}".format(e))
            sys.exit(1)

    # Return if Milvus has the collection
    def has_collection(self, collection_name):
        try:
            return utility.has_collection(collection_name)
        except Exception as e:
            LOGGER.error("Failed to load data to Milvus: {}".format(e))
            sys.exit(1)

    # Create milvus collection if not exists
    def create_collection(self, collection_name):
        try:
            if not self.has_collection(collection_name):
                field1 = FieldSchema(name="id", dtype=DataType.INT64, descrition="int64", is_primary=True,
                                     auto_id=False)
                field2 = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, descrition="float vector",
                                     dim=VECTOR_DIMENSION, is_primary=False)
                schema = CollectionSchema(fields=[field1, field2], description="collection description")
                self.collection = Collection(name=collection_name, schema=schema)
                LOGGER.debug("Create Milvus collection: {}".format(self.collection))
                return "OK"
            else:
                self.collection = Collection(collection_name)
                return "collection {} exists".format(collection_name)
        except Exception as e:
            LOGGER.error("Failed to load data to Milvus: {}".format(e))
            sys.exit(1)

    # Batch insert vectors to milvus collection
    def insert(self, collection_name, vectors, ids=None):
        try:
            self.create_collection(collection_name)
            # data = [vectors]
            self.collection.insert([ids, vectors])
            # vids = mr.primary_keys
            # self.collection.load()
            LOGGER.debug(
                "Insert vectors to Milvus in collection: {} with {} rows".format(collection_name, len(vectors)))
            return ids
        except Exception as e:
            LOGGER.error("Failed to load data to Milvus: {}".format(e))
            sys.exit(1)

    # Create IVF_FLAT index on milvus collection
    def create_index(self, collection_name, index_params):
        try:
            self.set_collection(collection_name)
            status = self.collection.create_index(field_name="embedding", index_params=index_params)
            if not status.code:
                self.collection.load()
                LOGGER.debug(
                    "Successfully create index in collection:{} with param:{}".format(collection_name, index_params))
                return status
            else:
                raise Exception(status.message)
        except Exception as e:
            LOGGER.error("Failed to create index: {}".format(e))
            sys.exit(1)

    # get index info
    def get_index_params(self, collection_name):
        self.set_collection(collection_name)
        return [index.params for index in self.collection.indexes]

    # Delete Milvus collection
    def delete_collection(self, collection_name):
        try:
            self.set_collection(collection_name)
            self.collection.drop()
            LOGGER.debug("Successfully drop collection!")
            return "ok"
        except Exception as e:
            LOGGER.error("Failed to drop collection: {}".format(e))
            sys.exit(1)

    # Search vector in milvus collection
    def search_vectors(self, collection_name, vectors, top_k, search_params):
        try:
            self.set_collection(collection_name)
            # search_params = {"metric_type": METRIC_TYPE, "params": {"nprobe": nprobe}}
            # data = [vectors]
            res = self.collection.search(vectors, anns_field="embedding", param=search_params, limit=top_k)
            LOGGER.debug("Successfully search in collection: {}".format(res))
            return res
        except Exception as e:
            LOGGER.error("Failed to search vectors in Milvus: {}".format(e))
            sys.exit(1)

    # Get the number of milvus collection
    def count(self, collection_name):
        try:
            self.set_collection(collection_name)
            num = self.collection.num_entities
            LOGGER.debug("Successfully get the num:{} of the collection:{}".format(num, collection_name))
            return num
        except Exception as e:
            LOGGER.error("Failed to count vectors in Milvus: {}".format(e))
            sys.exit(1)

    def create_partition(self, collection_name, partition_name):
        self.set_collection(collection_name)
        if self.collection.has_partition(partition_name):
            return "This partition {} exists".format(partition_name)
        else:
            partition = self.collection.create_partition(partition_name)
            return partition

    def delete_index(self, collection_name):
        self.set_collection(collection_name)
        self.collection.drop_index()
        
    def load_data(self, collection_name):
        self.set_collection(collection_name)
        self.collection.load()
       
    def show_collection(self):
        return utility.list_collections()
    
    def get_loading_progress(self, collection_name):
        return utility.loading_progress(collection_name)
    
    def get_index_progress(self, collection_name):
        return utility.index_building_progress(collection_name)
    
    def release_mem(self, collection_name):
        self.set_collection(collection_name)
        return self.collection.release()
