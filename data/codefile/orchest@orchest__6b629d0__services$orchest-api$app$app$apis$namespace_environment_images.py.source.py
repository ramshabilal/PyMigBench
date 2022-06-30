import logging

from docker import errors
from flask_restplus import Namespace, Resource

import app.models as models
from _orchest.internals import config as _config
from _orchest.internals.utils import docker_images_list_safe, docker_images_rm_safe
from app.apis.namespace_environment_builds import (
    delete_project_builds,
    delete_project_environment_builds,
)
from app.apis.namespace_experiments import stop_experiment
from app.apis.namespace_runs import stop_pipeline_run
from app.connections import docker_client
from app.utils import (
    experiments_using_environment,
    interactive_runs_using_environment,
    is_environment_in_use,
    register_schema,
    remove_if_dangling,
)

api = Namespace("environment-images", description="Managing environment images")
api = register_schema(api)


@api.route(
    "/<string:project_uuid>/<string:environment_uuid>",
)
@api.param("project_uuid", "UUID of the project")
@api.param("environment_uuid", "UUID of the environment")
class EnvironmentImage(Resource):
    @api.doc("delete-environment-image")
    def delete(self, project_uuid, environment_uuid):
        """Removes an environment image given project_uuid and image_uuid

        Will stop any run or experiment making use of this environment.
        """
        image_name = _config.ENVIRONMENT_IMAGE_NAME.format(
            project_uuid=project_uuid, environment_uuid=environment_uuid
        )

        # stop all interactive runs making use of the environment
        int_runs = interactive_runs_using_environment(project_uuid, environment_uuid)
        for run in int_runs:
            stop_pipeline_run(run.run_uuid)

        # stop all experiments making use of the environment
        exps = experiments_using_environment(project_uuid, environment_uuid)
        for exp in exps:
            stop_experiment(exp.experiment_uuid)

        # cleanup references to the builds and dangling images
        # of this environment
        delete_project_environment_builds(project_uuid, environment_uuid)
        delete_project_environment_dangling_images(project_uuid, environment_uuid)

        # try with repeat because there might be a race condition
        # where the aborted runs are still using the image
        docker_images_rm_safe(docker_client, image_name)

        return (
            {"message": f"Environment image {image_name} was successfully deleted"},
            200,
        )


@api.route(
    "/in-use/<string:project_uuid>/<string:environment_uuid>",
)
@api.param("project_uuid", "UUID of the project")
@api.param("environment_uuid", "UUID of the environment")
class EnvironmentImageInUse(Resource):
    @api.doc("is-environment-in-use")
    def get(self, project_uuid, environment_uuid):
        in_use = is_environment_in_use(project_uuid, environment_uuid)
        return {"message": in_use, "in_use": in_use}, 200


@api.route(
    "/dangling/<string:project_uuid>/<string:environment_uuid>",
)
@api.param("project_uuid", "UUID of the project")
@api.param("environment_uuid", "UUID of the environment")
class ProjectEnvironmentDanglingImages(Resource):
    @api.doc("delete-project-environment-dangling-images")
    def delete(self, project_uuid, environment_uuid):
        """Removes dangling images related to a project and environment.
        Dangling images are images that have been left nameless and
        tag-less and which are not referenced by any run
        or experiment which are pending or running."""

        delete_project_environment_dangling_images(project_uuid, environment_uuid)
        return {"message": "Successfully removed dangling images"}, 200


def delete_project_environment_images(project_uuid):
    """Delete environment images of a project.

    All environment images related to the project are removed
    from the environment, running environment builds are stopped
    and removed from the db. Dangling docker images are also removed.

    Args:
        project_uuid:
    """

    # cleanup references to the builds and dangling images
    # of all environments of this project
    delete_project_builds(project_uuid)
    delete_project_dangling_images(project_uuid)

    filters = {
        "label": [
            f"_orchest_env_build_is_intermediate=0",
            f"_orchest_project_uuid={project_uuid}",
        ]
    }
    images_to_remove = docker_images_list_safe(docker_client, filters=filters)

    image_remove_exceptions = []
    # try with repeat because there might be a race condition
    # where the aborted runs are still using the image
    for img in images_to_remove:
        docker_images_rm_safe(docker_client, img.id)


def delete_project_dangling_images(project_uuid):
    """Removes dangling images related to a project.

    Dangling images are images that have been left nameless and
    tag-less and which are not referenced by any run
    or experiment which are pending or running.

    Args:
        project_uuid:
    """
    # look only through runs belonging to the project
    filters = {
        "label": [
            f"_orchest_env_build_is_intermediate=0",
            f"_orchest_project_uuid={project_uuid}",
        ]
    }

    project_images = docker_images_list_safe(docker_client, filters=filters)

    for docker_img in project_images:
        remove_if_dangling(docker_img)


def delete_project_environment_dangling_images(project_uuid, environment_uuid):
    """Removes dangling images related to an environment.

    Dangling images are images that have been left nameless and
    tag-less and which are not referenced by any run
    or experiment which are pending or running.

    Args:
        project_uuid:
        environment_uuid:
    """
    # look only through runs belonging to the project
    # consider only docker ids related to the environment_uuid
    filters = {
        "label": [
            f"_orchest_env_build_is_intermediate=0",
            f"_orchest_project_uuid={project_uuid}",
            f"_orchest_environment_uuid={environment_uuid}",
        ]
    }

    project_env_images = docker_images_list_safe(docker_client, filters=filters)

    for docker_img in project_env_images:
        remove_if_dangling(docker_img)
