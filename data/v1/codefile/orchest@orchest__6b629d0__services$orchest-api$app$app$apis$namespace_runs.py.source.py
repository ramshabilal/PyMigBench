"""API endpoint to manage runs.

Note: "run" is short for "interactive pipeline run".
"""
import logging
import uuid

from celery.contrib.abortable import AbortableAsyncResult
from docker import errors
from flask import abort, current_app, request
from flask_restplus import Namespace, Resource, marshal

import app.models as models
from app import schema
from app.celery_app import make_celery
from app.connections import db
from app.core.pipelines import construct_pipeline
from app.utils import lock_environment_images_for_run, register_schema, update_status_db

api = Namespace("runs", description="Manages interactive pipeline runs")
api = register_schema(api)


@api.route("/")
class RunList(Resource):
    @api.doc("get_runs")
    @api.marshal_with(schema.interactive_runs)
    def get(self):
        """Fetches all (interactive) pipeline runs.

        These pipeline runs are either pending, running or have already
        completed.
        """

        query = models.InteractivePipelineRun.query

        # Ability to query a specific runs given the `pipeline_uuid` or `project_uuid`
        # through the URL (using `request.args`).
        if "pipeline_uuid" in request.args and "project_uuid" in request.args:
            query = query.filter_by(
                pipeline_uuid=request.args.get("pipeline_uuid")
            ).filter_by(project_uuid=request.args.get("project_uuid"))
        elif "project_uuid" in request.args:
            query = query.filter_by(project_uuid=request.args.get("project_uuid"))

        runs = query.all()
        return {"runs": [run.__dict__ for run in runs]}, 200

    @api.doc("start_run")
    @api.expect(schema.interactive_run_spec)
    def post(self):
        """Starts a new (interactive) pipeline run."""
        post_data = request.get_json()
        post_data["run_config"]["run_endpoint"] = "runs"

        pipeline = construct_pipeline(**post_data)

        # specify the task_id beforehand to avoid race conditions
        # between the task and its presence in the db
        task_id = str(uuid.uuid4())

        # NOTE: we are setting the status of the run ourselves without
        # using the option of celery to get the status of tasks. This
        # way we do not have to configure a backend (where the default
        # of "rpc://" does not give the results we would want).
        run = {
            "run_uuid": task_id,
            "pipeline_uuid": pipeline.properties["uuid"],
            "project_uuid": post_data["project_uuid"],
            "status": "PENDING",
        }
        db.session.add(models.InteractivePipelineRun(**run))
        # need to flush because otherwise the bulk insertion of pipeline
        # steps will lead to foreign key errors
        # https://docs.sqlalchemy.org/en/13/orm/persistence_techniques.html#bulk-operations-caveats
        db.session.flush()

        # Set an initial value for the status of the pipeline steps that
        # will be run.
        step_uuids = [s.properties["uuid"] for s in pipeline.steps]

        pipeline_steps = []
        for step_uuid in step_uuids:
            pipeline_steps.append(
                models.PipelineRunStep(
                    **{"run_uuid": task_id, "step_uuid": step_uuid, "status": "PENDING"}
                )
            )
        db.session.bulk_save_objects(pipeline_steps)
        db.session.commit()
        run["pipeline_steps"] = pipeline_steps

        # get docker ids of images to use and make it so that the images
        # will not be deleted in case they become outdated by an
        # environment rebuild
        try:
            env_uuid_docker_id_mappings = lock_environment_images_for_run(
                task_id,
                post_data["project_uuid"],
                pipeline.get_environments(),
            )
        except errors.ImageNotFound as e:
            logging.error(
                f"Pipeline was referencing environments for "
                f"which an image does not exist, {e}"
            )

            # simple way to update both in memory objects
            # and the db while avoiding multiple update statements
            # (1 for each object)
            # TODO: make it so that the client does not rely
            # on SUCCESS as a status
            run["status"] = "SUCCESS"
            for step in run["pipeline_steps"]:
                step.status = "FAILURE"
            models.InteractivePipelineRun.query.filter_by(run_uuid=task_id).update(
                {"status": "SUCCESS"}
            )
            models.PipelineRunStep.query.filter_by(run_uuid=task_id).update(
                {"status": "FAILURE"}
            )
            db.session.commit()

            return {
                "message": "Failed to start interactive run because not all referenced environments are available."
            }, 500

        # Create Celery object with the Flask context and construct the
        # kwargs for the job.
        celery = make_celery(current_app)
        run_config = post_data["run_config"]
        run_config["env_uuid_docker_id_mappings"] = env_uuid_docker_id_mappings
        celery_job_kwargs = {
            "pipeline_definition": pipeline.to_dict(),
            "project_uuid": post_data["project_uuid"],
            "run_config": run_config,
        }

        # Start the run as a background task on Celery. Due to circular
        # imports we send the task by name instead of importing the
        # function directly.
        res = celery.send_task(
            "app.core.tasks.run_pipeline", kwargs=celery_job_kwargs, task_id=task_id
        )

        # NOTE: this is only if a backend is configured.  The task does
        # not return anything. Therefore we can forget its result and
        # make sure that the Celery backend releases recourses (for
        # storing and transmitting results) associated to the task.
        # Uncomment the line below if applicable.
        res.forget()
        return marshal(run, schema.interactive_run), 201


@api.route("/<string:run_uuid>")
@api.param("run_uuid", "UUID of Run")
@api.response(404, "Run not found")
class Run(Resource):
    @api.doc("get_run")
    @api.marshal_with(schema.interactive_run, code=200)
    def get(self, run_uuid):
        """Fetches an interactive pipeline run given its UUID."""
        run = models.InteractivePipelineRun.query.filter_by(
            run_uuid=run_uuid
        ).one_or_none()
        if run is None:
            abort(404, description="Run not found")
        return run.__dict__

    @api.doc("set_run_status")
    @api.expect(schema.status_update)
    def put(self, run_uuid):
        """Sets the status of a pipeline run."""
        post_data = request.get_json()

        res = models.InteractivePipelineRun.query.filter_by(run_uuid=run_uuid).update(
            {"status": post_data["status"]}
        )

        if res:
            db.session.commit()

        return {"message": "Status was updated successfully"}, 200

    @api.doc("delete_run")
    @api.response(200, "Run terminated")
    def delete(self, run_uuid):
        """Stops a pipeline run given its UUID."""
        if stop_pipeline_run(run_uuid):
            return {"message": "Run termination was successful"}, 200
        else:
            return {"message": "Run does not exist or is not running"}, 400


@api.route("/<string:run_uuid>/<string:step_uuid>")
@api.param("run_uuid", "UUID of Run")
@api.param("step_uuid", "UUID of Pipeline Step")
@api.response(404, "Pipeline step not found")
class StepStatus(Resource):
    @api.doc("get_step_status")
    @api.marshal_with(schema.pipeline_run_pipeline_step, code=200)
    def get(self, run_uuid, step_uuid):
        """Fetches the status of a pipeline step of a specific run."""
        step = models.PipelineRunStep.query.get_or_404(
            ident=(run_uuid, step_uuid),
            description="Run and step combination not found",
        )
        return step.__dict__

    @api.doc("set_step_status")
    @api.expect(schema.status_update)
    def put(self, run_uuid, step_uuid):
        """Sets the status of a pipeline step."""
        status_update = request.get_json()

        # TODO: first check the status and make sure it says PENDING or
        #       whatever. Because if is empty then this would write it
        #       and then get overwritten afterwards with "PENDING".
        filter_by = {"run_uuid": run_uuid, "step_uuid": step_uuid}
        update_status_db(
            status_update, model=models.PipelineRunStep, filter_by=filter_by
        )

        return {"message": "Status was updated successfully"}, 200


def stop_pipeline_run(run_uuid) -> bool:
    """Stop a pipeline run.

    The run will cancelled if not running yet, otherwise
    it will be aborted.

    Args:
        run_uuid:

    Returns:
        True if a cancellation was issued to the run, false if the
        run did not exist or was not PENDING/STARTED.
    """
    interactive_run = models.PipelineRun.query.filter(
        models.PipelineRun.status.in_(["PENDING", "STARTED"]),
        models.PipelineRun.run_uuid == run_uuid,
    ).one_or_none()
    if interactive_run is None:
        return False

    celery_app = make_celery(current_app)
    res = AbortableAsyncResult(run_uuid, app=celery_app)

    # it is responsibility of the task to terminate by reading
    # it's aborted status
    res.abort()

    celery_app.control.revoke(run_uuid)
    # TODO: possibly set status of steps and Run to "ABORTED"
    #  note that a race condition would be present since the
    # task will try to set the status as well

    return True
