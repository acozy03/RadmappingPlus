Tables in the database:
        1. rad_avg_monthly_rvu (
            radiologist_id uuid,
            jan float8,
            feb float8,
            mar float8,
            apr float8,
            may float8,
            jun float8,
            jul float8,
            aug float8,
            sep float8,
            oct float8,
            nov float8,
            dec float8
        )

        2. vesta_contacts (
            id uuid,
            name text,
            department text,
            contact_number text,
            extension_number text,
            email text,
            additional_info text,
            created_at timestamptz,
            updated_at timestamptz
        )

        3. certifications (
            id uuid,
            radiologist_id uuid REFERENCES radiologists(id),
            state text,
            expiration_date date,
            status text,
            specialty text,
            tags text
        )

        4. monthly_schedule (
            id uuid,
            radiologist_id uuid REFERENCES radiologists(id),
            start_time time,
            end_time time,
            schedule_details text,
            start_date date,
            end_date date,
            break_start time,
            break_end time
        )

        5. users (
            id uuid,
            email text,
            password text,
            role text
        )

        6. radiologists (
            id uuid,
            name text,
            pacs text,
            primary_contact_method text,
            phone text,
            email text,
            active_status bool,
            schedule_info_est text,
            additional_info text,
            credentialing_contact text,
            rad_guidelines text,
            modalities text,
            timezone text,
            reads_routines bool
        )

        7. capacity_per_hour (
            date date,
            hour int4,
            total_rvus float8
        )

        8. doctor_facility_assignments (
            id uuid,
            radiologist_id uuid REFERENCES radiologists(id),
            facility_id uuid REFERENCES facilities(id),
            can_read bool,
            stipulations text,
            does_stats bool,
            does_routines bool,
            notes text
        )

        9. specialty_permissions (
            id uuid,
            radiologist_id uuid REFERENCES radiologists(id),
            specialty_id uuid REFERENCES specialty_studies(id),
            can_read bool
        )

        10. specialty_studies (
            id uuid,
            name text,
            description text
        )

        11. vacations (
            id uuid,
            radiologist_id uuid REFERENCES radiologists(id),
            start_date date,
            end_date date,
            comments text
        )

        12. facilities (
            id uuid,
            name text,
            pacs text,
            location text,
            modalities_assignment_period text,
            tat_definition text,
            active_status text,
            modalities text
        )

        13. facility_contact_assignments (
            id uuid,
            facility_id uuid REFERENCES facilities(id),
            contact_name text,
            email text,
            phone text,
            comments text,
            role text
        )

        14. pinned_doctors (
            id uuid,
            user_id uuid REFERENCES users(id),
            doctor_id uuid REFERENCES radiologists(id),
            created_at timestamptz
        )